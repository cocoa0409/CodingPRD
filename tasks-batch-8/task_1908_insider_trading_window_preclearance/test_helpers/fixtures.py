"""Composite setup helpers for the insider-trading compliance domain.

Every helper builds its preconditions from scratch against a fresh server using
only PRD-declared endpoints. Identity threading: entity-backed roles always act
with headers built from the actual CoveredPerson id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_LOGICAL_CLOCK
from .factories import (
    create_attestation_payload,
    create_blackout_window_payload,
    create_covered_person_payload,
    create_deal_payload,
    create_exception_request_payload,
    create_preclearance_request_payload,
    create_restricted_list_entry_payload,
    create_tenb5_plan_payload,
    create_trade_confirmation_payload,
)
from .test_users import (
    make_compliance_officer_headers,
    make_committee_member_headers,
    make_insider_headers,
    make_legal_admin_headers,
)

DEFAULT_CLOCK = DEFAULT_LOGICAL_CLOCK
FUTURE_DUE_DATE = "2026-12-31T00:00:00Z"


# ---------------------------------------------------------------------------
# Role header helpers (identity threading)
# ---------------------------------------------------------------------------

def admin_headers():
    return make_legal_admin_headers()


def as_insider(person: dict) -> dict:
    return make_insider_headers(person["id"])


def as_officer(officer: dict) -> dict:
    return make_compliance_officer_headers(officer["id"])


def as_member(member: dict) -> dict:
    return make_committee_member_headers(member["id"])


# ---------------------------------------------------------------------------
# Tier 0: clock + basic entities
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Set the server's logical clock (LegalAdmin-only, PRD §2.4)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, admin_headers())
    )


def create_person(full_name, email, designation="EMPLOYEE", department="Ops") -> dict:
    """Onboard a covered person (LegalAdmin). Returns the created person."""
    payload = create_covered_person_payload(
        full_name=full_name, email=email, designation=designation, department=department
    )
    return get_success_data(
        api_client.create_covered_person(payload, admin_headers()), expected_status=201
    )


def create_officer(email, designation="EMPLOYEE") -> dict:
    """A covered person used as the acting ComplianceOfficer."""
    return create_person("Compliance Officer", email, designation, "Legal")


def get_person(person_id) -> dict:
    return get_success_data(api_client.get_covered_person(person_id, admin_headers()))


# ---------------------------------------------------------------------------
# Tier 1: attestation currency (policy ack + annual training)
# ---------------------------------------------------------------------------

def complete_attestation_for(person: dict, kind: str,
                             period_year: int = 2026,
                             due_date: str = FUTURE_DUE_DATE) -> dict:
    """Assign (LegalAdmin) then complete (Insider owner) an attestation."""
    att = get_success_data(
        api_client.create_attestation(
            create_attestation_payload(
                covered_person_id=person["id"],
                kind=kind,
                period_year=period_year,
                due_date=due_date,
            ),
            admin_headers(),
        ),
        expected_status=201,
    )
    return get_success_data(
        api_client.complete_attestation(att["id"], as_insider(person))
    )


def make_person_current(person: dict) -> dict:
    """Complete POLICY_ACK and ANNUAL_TRAINING for the person so both currency
    flags read true; returns the re-read person (version advanced)."""
    complete_attestation_for(person, "POLICY_ACK")
    complete_attestation_for(person, "ANNUAL_TRAINING")
    return get_person(person["id"])


def create_current_person(full_name, email, designation="EMPLOYEE",
                          department="Ops") -> dict:
    """Fresh person who is policy-ack and training current."""
    return make_person_current(create_person(full_name, email, designation, department))


# ---------------------------------------------------------------------------
# Tier 2: preclearance workflow
# ---------------------------------------------------------------------------

def create_submitted_request(person: dict, ticker="ACME", side="BUY", quantity=10,
                             proposed_trade_date="2026-08-20T00:00:00Z",
                             exception_id=None) -> dict:
    payload = create_preclearance_request_payload(
        covered_person_id=person["id"],
        security_ticker=ticker,
        trade_side=side,
        quantity=quantity,
        proposed_trade_date=proposed_trade_date,
    )
    if exception_id is not None:
        payload["exception_id"] = exception_id
    return get_success_data(
        api_client.create_preclearance_request(payload, as_insider(person)),
        expected_status=201,
    )


def create_under_review_request(person: dict, officer: dict, **kwargs) -> dict:
    """SUBMITTED -> UNDER_REVIEW. Returns the reviewed request (version 2)."""
    req = create_submitted_request(person, **kwargs)
    return get_success_data(
        api_client.review_preclearance_request(req["id"], as_officer(officer))
    )


def decide_request(request_or_id, officer: dict, outcome="APPROVE",
                   expected_version=None, denial_reason=None):
    """Raw decision call; returns the response for caller-side validation."""
    request_id = (
        request_or_id["id"] if isinstance(request_or_id, dict) else request_or_id
    )
    payload = {"outcome": outcome}
    if expected_version is not None:
        payload["expected_preclearance_version"] = expected_version
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    return api_client.decide_preclearance_request(
        request_id, payload, as_officer(officer)
    )


def create_approved_request(person: dict, officer: dict, quantity=100, ticker="ACME",
                            side="BUY", proposed_trade_date="2026-08-02T00:00:00Z",
                            exception_id=None) -> dict:
    """Full chain: SUBMITTED -> UNDER_REVIEW -> APPROVED. Returns approved request."""
    reviewed = create_under_review_request(
        person, officer, ticker=ticker, side=side, quantity=quantity,
        proposed_trade_date=proposed_trade_date, exception_id=exception_id,
    )
    return get_success_data(
        decide_request(reviewed, officer, "APPROVE", reviewed["version"])
    )


def get_request(request_id, officer=None) -> dict:
    headers = as_officer(officer) if officer else admin_headers()
    return get_success_data(api_client.get_preclearance_request(request_id, headers))


# ---------------------------------------------------------------------------
# Tier 2: blackout windows / restricted list / deals
# ---------------------------------------------------------------------------

def create_quarterly_window(officer: dict, start_at, end_at, fiscal_year=2026,
                            fiscal_quarter="Q3") -> dict:
    return get_success_data(
        api_client.create_blackout_window(
            create_blackout_window_payload(
                kind="QUARTERLY", fiscal_year=fiscal_year,
                fiscal_quarter=fiscal_quarter, start_at=start_at, end_at=end_at,
            ),
            as_officer(officer),
        ),
        expected_status=201,
    )


def create_event_window(officer: dict, ticker, start_at, end_at) -> dict:
    return get_success_data(
        api_client.create_blackout_window(
            create_blackout_window_payload(
                kind="EVENT_DRIVEN", security_ticker=ticker,
                start_at=start_at, end_at=end_at,
            ),
            as_officer(officer),
        ),
        expected_status=201,
    )


def create_manual_restricted_entry(officer: dict, ticker, note=None) -> dict:
    payload = create_restricted_list_entry_payload(security_ticker=ticker)
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.create_restricted_list_entry(payload, as_officer(officer)),
        expected_status=201,
    )


def create_deal(officer: dict, codename, ticker, deal_type="MERGER",
                event_blackout_start=None, event_blackout_end=None) -> dict:
    payload = create_deal_payload(
        codename=codename, deal_type=deal_type, security_ticker=ticker
    )
    if event_blackout_start is not None:
        payload["event_blackout_start"] = event_blackout_start
    if event_blackout_end is not None:
        payload["event_blackout_end"] = event_blackout_end
    return get_success_data(
        api_client.create_deal(payload, as_officer(officer)), expected_status=201
    )


def activate_deal(officer: dict, deal_id) -> dict:
    return get_success_data(api_client.activate_deal(deal_id, as_officer(officer)))


def close_deal(officer: dict, deal_id, outcome) -> dict:
    return get_success_data(
        api_client.close_deal(deal_id, {"outcome": outcome}, as_officer(officer))
    )


def list_active_entries_for_ticker(officer: dict, ticker) -> list:
    data = get_success_data(
        api_client.list_restricted_list_entries(
            as_officer(officer), params={"security_ticker": ticker, "status": "ACTIVE"}
        )
    )
    assert isinstance(data, list), f"expected list payload, got {type(data)}"
    return data


# ---------------------------------------------------------------------------
# Tier 2: exception requests
# ---------------------------------------------------------------------------

def create_submitted_exception(requester: dict, ticker="ACME", quantity=1000,
                               hardship_reason="hardship") -> dict:
    return get_success_data(
        api_client.create_exception_request(
            create_exception_request_payload(
                covered_person_id=requester["id"],
                security_ticker=ticker,
                quantity=quantity,
                hardship_reason=hardship_reason,
            ),
            as_insider(requester),
        ),
        expected_status=201,
    )


def vote_exception(member: dict, exception_id, vote):
    """Raw vote call; returns the response for caller-side validation."""
    return api_client.vote_exception_request(
        exception_id, {"vote": vote}, as_member(member)
    )


def create_approved_exception(requester: dict, member1: dict, member2: dict,
                              ticker="ACME", quantity=1000,
                              hardship_reason="hardship") -> dict:
    """Exception decided APPROVED by a two-member quorum."""
    exc = create_submitted_exception(requester, ticker, quantity, hardship_reason)
    get_success_data(vote_exception(member1, exc["id"], "APPROVE"))
    get_success_data(vote_exception(member2, exc["id"], "APPROVE"))
    return get_success_data(
        api_client.get_exception_request(exc["id"], admin_headers())
    )


# ---------------------------------------------------------------------------
# Tier 2/3: 10b5-1 plans
# ---------------------------------------------------------------------------

def create_draft_plan(person: dict, ticker="ACME", total_quantity=300,
                      first_trade_date="2026-09-01T00:00:00Z") -> dict:
    """Create a DRAFT plan carrying the owner's current version as OCC guard."""
    fresh = get_person(person["id"])
    return get_success_data(
        api_client.create_tenb5_plan(
            create_tenb5_plan_payload(
                covered_person_id=person["id"],
                security_ticker=ticker,
                total_quantity=total_quantity,
                first_trade_date=first_trade_date,
                expected_covered_person_version=fresh["version"],
            ),
            as_insider(person),
        ),
        expected_status=201,
    )


def create_submitted_plan(person: dict, **kwargs) -> dict:
    plan = create_draft_plan(person, **kwargs)
    return get_success_data(api_client.submit_tenb5_plan(plan["id"], as_insider(person)))


def create_approved_plan(person: dict, officer: dict, **kwargs) -> dict:
    submitted = create_submitted_plan(person, **kwargs)
    return get_success_data(
        api_client.decide_tenb5_plan(
            submitted["id"], {"outcome": "APPROVE"}, as_officer(officer)
        )
    )


def activate_plan_via_sweep(officer: dict, at_iso) -> dict:
    """Advance the clock and run the sweep so APPROVED plans past cooling-off
    move to ACTIVE. Returns the sweep counts."""
    set_logical_clock(at_iso)
    return run_sweep(officer)


# ---------------------------------------------------------------------------
# Tier 2: trade confirmations / violation cases / sweep
# ---------------------------------------------------------------------------

def ingest_confirmation(officer: dict, person: dict, ticker="ACME", side="BUY",
                        quantity=100, price=10.00,
                        trade_date="2026-08-02T00:00:00Z", broker_ref="BR-1") -> dict:
    """Ingest a confirmation; returns it with its resolved (post-match) status."""
    return get_success_data(
        api_client.create_trade_confirmation(
            create_trade_confirmation_payload(
                covered_person_id=person["id"],
                security_ticker=ticker,
                trade_side=side,
                quantity=quantity,
                price=price,
                trade_date=trade_date,
                broker_ref=broker_ref,
            ),
            as_officer(officer),
        ),
        expected_status=201,
    )


def find_case_for_confirmation(officer: dict, confirmation_id) -> dict:
    """Locate the violation case referencing a confirmation."""
    data = get_success_data(
        api_client.list_violation_cases(
            as_officer(officer), params={"trade_confirmation_id": confirmation_id}
        )
    )
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly 1 case for confirmation {confirmation_id}, got {data}"
    )
    return data[0]


def flag_confirmation_with_case(officer: dict, person: dict, **kwargs):
    """Ingest an unmatched confirmation (FLAGGED) and return (confirmation, case)."""
    conf = ingest_confirmation(officer, person, **kwargs)
    assert conf["status"] == "FLAGGED", f"expected FLAGGED, got {conf['status']}"
    case = find_case_for_confirmation(officer, conf["id"])
    return conf, case


def case_action(officer: dict, case_id, action) -> dict:
    return get_success_data(
        api_client.act_on_violation_case(case_id, {"action": action}, as_officer(officer))
    )


def get_case(case_id, officer=None) -> dict:
    headers = as_officer(officer) if officer else admin_headers()
    return get_success_data(api_client.get_violation_case(case_id, headers))


def run_sweep(officer: dict) -> dict:
    return get_success_data(api_client.run_compliance_sweep(as_officer(officer)))
