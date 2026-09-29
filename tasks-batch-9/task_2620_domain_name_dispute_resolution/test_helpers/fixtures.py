"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because each test runs against an empty database. Setup calls use
the lenient validator so a broken precondition reports as a setup failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_EPOCH
from .factories import (
    appointment_payload,
    case_payload,
    complainant_payload,
    conflict_screening_payload,
    court_challenge_payload,
    decision_payload,
    deficiency_notice_payload,
    delivery_payload,
    domain_payload,
    fee_transaction_payload,
    ground_payload,
    notification_payload,
    panelist_payload,
    publish_payload,
    registrar_payload,
    resolve_challenge_payload,
    response_payload,
    verification_response_payload,
    vote_payload,
    waiver_payload,
)
from .test_users import (
    CASE_MANAGER,
    CASE_MANAGER_ALT,
    CASE_MANAGER_ONE,
    PROVIDER_ADMIN,
    make_case_manager_headers,
    make_complainant_headers,
    make_panelist_headers,
    make_registrar_headers,
    make_respondent_headers,
)

VERIFIED_REGISTRANT_EMAIL = "registrant@true.example"
VERIFIED_REGISTRANT_NAME = "True Registrant Ltd"
MANDATORY_GROUNDS = ["TRADEMARK_RIGHTS", "NO_LEGITIMATE_INTEREST", "BAD_FAITH"]


# --- The logical clock ---------------------------------------------------

def set_clock(instant: str) -> dict:
    """Move the server-held logical clock to `instant`."""
    return get_success_data(api_client.set_clock({"current_utc": instant}, PROVIDER_ADMIN))


def reset_clock_to_epoch() -> dict:
    return set_clock(CLOCK_EPOCH)


def run_sweep() -> dict:
    """Run the administrative deadline sweep and return its four counters."""
    return get_success_data(api_client.run_deadline_sweep(PROVIDER_ADMIN))


# --- Reference registers -------------------------------------------------

def admit_registrar(iana_id: str = "IANA-1001", **overrides) -> dict:
    payload = registrar_payload(iana_id=iana_id, **overrides)
    return get_success_data(api_client.create_registrar(payload, PROVIDER_ADMIN))


def suspend_registrar(registrar_id: str) -> dict:
    return get_success_data(
        api_client.set_registrar_status(registrar_id, {"status": "SUSPENDED"}, PROVIDER_ADMIN)
    )


def register_domain(registrar_id: str, domain_name: str = "disputed.example", **overrides) -> dict:
    payload = domain_payload(registrar_id, domain_name, **overrides)
    return get_success_data(api_client.create_domain(payload, PROVIDER_ADMIN))


def register_complainant(**overrides) -> dict:
    payload = complainant_payload(**overrides)
    return get_success_data(api_client.create_complainant(payload, CASE_MANAGER))


def admit_panelist(**overrides) -> dict:
    payload = panelist_payload(**overrides)
    return get_success_data(api_client.create_panelist(payload, PROVIDER_ADMIN))


def set_availability(panelist_id: str, headers=None, **payload) -> dict:
    return get_success_data(
        api_client.set_panelist_availability(panelist_id, payload, headers or PROVIDER_ADMIN)
    )


def set_domain_lock(domain_id: str, lock_status: str, headers=None) -> dict:
    return get_success_data(
        api_client.set_domain_lock(domain_id, {"lock_status": lock_status}, headers or PROVIDER_ADMIN)
    )


# --- Readers -------------------------------------------------------------

def read_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, CASE_MANAGER))


def case_version(case_id: str) -> int:
    """Re-read the case's stored version, as a version-pinned write requires."""
    return read_case(case_id)["version"]


def read_domain(domain_id: str) -> dict:
    return get_success_data(api_client.get_domain(domain_id, PROVIDER_ADMIN))


def read_complainant(complainant_id: str) -> dict:
    return get_success_data(api_client.get_complainant(complainant_id, CASE_MANAGER))


def read_panelist(panelist_id: str) -> dict:
    return get_success_data(api_client.get_panelist(panelist_id, PROVIDER_ADMIN))


def read_appointment(appointment_id: str) -> dict:
    return get_success_data(api_client.get_appointment(appointment_id, CASE_MANAGER))


def read_decision(decision_id: str) -> dict:
    return get_success_data(api_client.get_decision(decision_id, CASE_MANAGER))


def read_registrar(registrar_id: str) -> dict:
    return get_success_data(api_client.get_registrar(registrar_id, PROVIDER_ADMIN))


def load_of(panelist_id: str) -> int:
    return read_panelist(panelist_id)["active_case_load"]


# --- Tier 2: the docket a complaint needs before it can be filed ---------

def build_docket(
    iana_id: str = "IANA-1001",
    domain_name: str = "disputed.example",
    country_code: str = "FR",
    verification_response_hours: int = None,
    legal_name: str = "Marque SA",
    registrar_name: str = "Northwind Registrar",
) -> dict:
    """Accredit a registrar, register its domain and register a complainant."""
    registrar_overrides = {"name": registrar_name}
    if verification_response_hours is not None:
        registrar_overrides["verification_response_hours"] = verification_response_hours
    registrar = admit_registrar(iana_id=iana_id, **registrar_overrides)
    domain = register_domain(registrar["id"], domain_name)
    complainant = register_complainant(
        legal_name=legal_name,
        country_code=country_code,
        email="ip@%s" % domain_name,
    )
    return {"registrar": registrar, "domain": domain, "complainant": complainant}


def file_complaint(complainant: dict, domain: dict, **overrides) -> dict:
    """File a complaint as the owning complainant."""
    payload = case_payload(complainant["id"], domain["id"], **overrides)
    return get_success_data(
        api_client.create_case(payload, make_complainant_headers(complainant["id"]))
    )


def assert_ground_on_case(case: dict, complainant: dict, ground_type: str, **overrides) -> dict:
    payload = ground_payload(ground_type, **overrides)
    return get_success_data(
        api_client.create_ground(
            case["id"], payload, make_complainant_headers(complainant["id"])
        )
    )


def assert_all_mandatory_grounds(case: dict, complainant: dict, evidence_count: int = 2) -> list:
    """Assert one sufficient element per mandatory ground_type."""
    return [
        assert_ground_on_case(case, complainant, ground_type, evidence_count=evidence_count)
        for ground_type in MANDATORY_GROUNDS
    ]


def post_ledger_line(
    case_id: str,
    amount_cents: int,
    payer: str = "COMPLAINANT",
    kind: str = "FILING_FEE",
    reference: str = "WIRE-0001",
    headers=None,
) -> dict:
    payload = fee_transaction_payload(
        amount_cents, payer=payer, kind=kind, reference=reference
    )
    return get_success_data(
        api_client.create_fee_transaction(case_id, payload, headers or CASE_MANAGER)
    )


def fund_case_to_assessment(case_id: str) -> dict:
    """Post whatever each party still owes so paid_cents reaches the assessment."""
    case = read_case(case_id)
    complainant_gap = case["complainant_share_cents"] - case["complainant_paid_cents"]
    if complainant_gap > 0:
        post_ledger_line(
            case_id, complainant_gap, payer="COMPLAINANT",
            kind="PANEL_SUPPLEMENT", reference="WIRE-COMPLAINANT-BALANCE",
        )
    respondent_gap = case["respondent_share_cents"] - case["respondent_paid_cents"]
    if respondent_gap > 0:
        post_ledger_line(
            case_id, respondent_gap, payer="RESPONDENT",
            kind="PANEL_SUPPLEMENT", reference="WIRE-RESPONDENT-SUPPLEMENT",
        )
    return read_case(case_id)


# --- Tier 1 / Tier 3: walking a case along its lifecycle -----------------

def setup_filed_case(
    evidence_count: int = 2,
    pay_filing_fee: bool = True,
    **docket_and_case
) -> dict:
    """Docket + a FILED case carrying all three sufficient elements.

    Returns a bundle: registrar, domain, complainant, case, grounds.
    """
    docket_keys = (
        "iana_id", "domain_name", "country_code", "verification_response_hours",
        "legal_name", "registrar_name",
    )
    docket_args = {k: v for k, v in docket_and_case.items() if k in docket_keys}
    case_args = {k: v for k, v in docket_and_case.items() if k not in docket_keys}
    bundle = build_docket(**docket_args)
    case = file_complaint(bundle["complainant"], bundle["domain"], **case_args)
    grounds = assert_all_mandatory_grounds(
        case, bundle["complainant"], evidence_count=evidence_count
    )
    if pay_filing_fee:
        post_ledger_line(case["id"], case["complainant_share_cents"])
    bundle["case"] = read_case(case["id"])
    bundle["grounds"] = grounds
    return bundle


def clear_compliance(case_id: str, headers=None, reviewer_notes: str = "Filing complete.") -> dict:
    return get_success_data(
        api_client.clear_compliance(
            case_id, {"reviewer_notes": reviewer_notes}, headers or CASE_MANAGER
        )
    )


def first_verification(case_id: str) -> dict:
    """The verification row the clearance cascade minted, read off the case."""
    body = get_success_data(api_client.list_registrar_verifications(case_id, CASE_MANAGER))
    assert body, "clearance must have minted a verification request on the case"
    return body[0]


def setup_verification_pending_case(**kwargs) -> dict:
    """A cleared case in VERIFICATION_PENDING with its verification request."""
    clearing_headers = kwargs.pop("clearing_headers", None)
    bundle = setup_filed_case(**kwargs)
    clear_compliance(bundle["case"]["id"], headers=clearing_headers)
    bundle["verification"] = first_verification(bundle["case"]["id"])
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def answer_verification(bundle: dict, **overrides) -> dict:
    """The registrar of record discloses the registrant and attests the lock."""
    payload = verification_response_payload(**overrides)
    return get_success_data(
        api_client.respond_to_verification(
            bundle["case"]["id"],
            bundle["verification"]["id"],
            payload,
            make_registrar_headers(bundle["registrar"]["id"]),
        )
    )


def setup_notification_pending_case(**kwargs) -> dict:
    """A case whose registrar has answered: domain LOCKED, case NOTIFICATION_PENDING."""
    bundle = setup_verification_pending_case(**kwargs)
    bundle["verification"] = answer_verification(bundle)
    bundle["case"] = read_case(bundle["case"]["id"])
    bundle["domain"] = read_domain(bundle["domain"]["id"])
    return bundle


def dispatch_notification(case_id: str, channel: str = "EMAIL", **overrides) -> dict:
    payload = notification_payload(channel, **overrides)
    return get_success_data(api_client.create_notification(case_id, payload, CASE_MANAGER))


def setup_commenced_case(channel: str = "EMAIL", **kwargs) -> dict:
    """A COMMENCED case with one dispatched attempt and a provisional deadline."""
    bundle = setup_notification_pending_case(**kwargs)
    bundle["notification"] = dispatch_notification(bundle["case"]["id"], channel)
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def record_delivery(bundle: dict, outcome: str = "DELIVERED", **overrides) -> dict:
    payload = delivery_payload(outcome, **overrides)
    return get_success_data(
        api_client.record_delivery(
            bundle["case"]["id"], bundle["notification"]["id"], payload, CASE_MANAGER
        )
    )


def setup_delivered_case(channel: str = "EMAIL", deemed_received_at: str = None, **kwargs) -> dict:
    """A COMMENCED case whose attempt was DELIVERED, so the deadline is FINAL."""
    bundle = setup_commenced_case(channel=channel, **kwargs)
    overrides = {}
    if deemed_received_at is not None:
        overrides["deemed_received_at"] = deemed_received_at
    bundle["notification"] = record_delivery(bundle, "DELIVERED", **overrides)
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def file_response(bundle: dict, **overrides) -> dict:
    payload = response_payload(VERIFIED_REGISTRANT_EMAIL, **overrides)
    return get_success_data(
        api_client.create_response(bundle["case"]["id"], payload, make_respondent_headers())
    )


def setup_responded_case(requests_three_member_panel: bool = False, **kwargs) -> dict:
    """A RESPONSE_RECEIVED case, optionally re-priced by a three-member election."""
    bundle = setup_commenced_case(**kwargs)
    overrides = {}
    if requests_three_member_panel:
        overrides["requests_three_member_panel"] = True
    bundle["response"] = file_response(bundle, **overrides)
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def setup_defaulted_case(sweep_at: str, **kwargs) -> dict:
    """A COMMENCED case swept into DEFAULT once the deadline and grace lapsed."""
    bundle = setup_commenced_case(**kwargs)
    set_clock(sweep_at)
    bundle["sweep"] = run_sweep()
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


# --- Tier 3: constituting a panel ----------------------------------------

def nominate_seat(
    case_id: str,
    seat: str,
    panelist_id: str = None,
    nominated_by: str = "PROVIDER",
    headers=None,
    expected_case_version: int = None,
) -> dict:
    """Nominate a seat, pinning the case version freshly read for the write."""
    version = case_version(case_id) if expected_case_version is None else expected_case_version
    payload = appointment_payload(seat, version, nominated_by=nominated_by)
    if panelist_id is not None:
        payload["panelist_id"] = panelist_id
    return get_success_data(
        api_client.create_appointment(case_id, payload, headers or CASE_MANAGER)
    )


def screen_seat(appointment_id: str, panelist_id: str, **disclosures) -> dict:
    """The nominated neutral files conflict disclosures on their own seat."""
    payload = conflict_screening_payload(**disclosures)
    return get_success_data(
        api_client.screen_conflict(appointment_id, payload, make_panelist_headers(panelist_id))
    )


def waive_seat(appointment_id: str, headers=None, **overrides) -> dict:
    payload = waiver_payload(**overrides)
    return get_success_data(
        api_client.record_waiver(appointment_id, payload, headers or CASE_MANAGER)
    )


def replace_seat(appointment_id: str, replacement_panelist_id: str = None, headers=None, **overrides) -> dict:
    """Vacate a seat; the response reports the updated predecessor row."""
    payload = {"reason": overrides.pop("reason", "Seat vacated by the provider.")}
    if replacement_panelist_id is not None:
        payload["replacement_panelist_id"] = replacement_panelist_id
    payload.update(overrides)
    return get_success_data(
        api_client.replace_appointment(appointment_id, payload, headers or CASE_MANAGER)
    )


def seat_panelist_cleanly(case_id: str, seat: str, panelist: dict, nominated_by: str = "PROVIDER") -> dict:
    """Nominate a named neutral and screen with no disclosures, so the seat is taken."""
    appointment = nominate_seat(case_id, seat, panelist["id"], nominated_by=nominated_by)
    return screen_seat(appointment["id"], panelist["id"])


def admit_eligible_panelists(count: int, **overrides) -> list:
    """Admit `count` neutrals whose nationalities clash with nothing by default."""
    roster = [
        {"full_name": "Anna Bauer", "nationality_code": "DE", "roster_admitted_at": "2019-01-15T00:00:00Z"},
        {"full_name": "Marco Rossi", "nationality_code": "IT", "roster_admitted_at": "2019-02-20T00:00:00Z"},
        {"full_name": "Elena Ruiz", "nationality_code": "ES", "roster_admitted_at": "2019-03-25T00:00:00Z"},
        {"full_name": "Piet de Vries", "nationality_code": "NL", "roster_admitted_at": "2019-04-30T00:00:00Z"},
        {"full_name": "Ewa Kowalska", "nationality_code": "PL", "roster_admitted_at": "2020-06-01T00:00:00Z"},
    ]
    admitted = []
    for spec in roster[:count]:
        spec = dict(spec)
        spec.update(overrides)
        admitted.append(admit_panelist(**spec))
    return admitted


def setup_single_member_panel(**kwargs) -> dict:
    """A PANEL_CONSTITUTED single-member case with its SOLE seat accepted."""
    panelist_overrides = kwargs.pop("panelist_overrides", {})
    bundle = setup_responded_case(**kwargs)
    fund_case_to_assessment(bundle["case"]["id"])
    panelist_spec = {
        "full_name": "Anna Bauer",
        "nationality_code": "DE",
        "roster_admitted_at": "2019-01-15T00:00:00Z",
    }
    panelist_spec.update(panelist_overrides)
    panelist = admit_panelist(**panelist_spec)
    appointment = seat_panelist_cleanly(bundle["case"]["id"], "SOLE", panelist)
    bundle["panelists"] = [panelist]
    bundle["appointments"] = [appointment]
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def setup_three_member_panel(**kwargs) -> dict:
    """A PANEL_CONSTITUTED three-member case: all three seats accepted."""
    kwargs.setdefault("requests_three_member_panel", True)
    bundle = setup_responded_case(**kwargs)
    fund_case_to_assessment(bundle["case"]["id"])
    panelists = admit_eligible_panelists(3)
    seats = ["PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2"]
    appointments = [
        seat_panelist_cleanly(bundle["case"]["id"], seat, panelist)
        for seat, panelist in zip(seats, panelists)
    ]
    bundle["panelists"] = panelists
    bundle["appointments"] = appointments
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


# --- Tier 3 / Tier 5: deliberation, issuance and what follows ------------

def draft_decision(case_id: str, drafted_by_panelist_id: str, headers=None, **overrides) -> dict:
    """Open a decision draft, pinning the case version freshly read for the write."""
    version = overrides.pop("expected_case_version", None)
    if version is None:
        version = case_version(case_id)
    payload = decision_payload(version, drafted_by_panelist_id, **overrides)
    return get_success_data(
        api_client.create_decision(case_id, payload, headers or CASE_MANAGER)
    )


def cast_seat_vote(decision_id: str, panelist_id: str, seat: str, vote: str, **overrides) -> dict:
    payload = vote_payload(seat, vote, **overrides)
    return get_success_data(
        api_client.cast_vote(decision_id, payload, make_panelist_headers(panelist_id))
    )


def issue_decision(decision_id: str, headers=None) -> dict:
    return get_success_data(api_client.issue_decision(decision_id, headers or CASE_MANAGER))


def setup_issued_single_member_decision(vote: str = "TRANSFER", rdnh_vote: bool = None, **kwargs) -> dict:
    """A single-member case carried through to an ISSUED decision."""
    bundle = setup_single_member_panel(**kwargs)
    panelist = bundle["panelists"][0]
    decision = draft_decision(bundle["case"]["id"], panelist["id"])
    overrides = {} if rdnh_vote is None else {"rdnh_vote": rdnh_vote}
    cast_seat_vote(decision["id"], panelist["id"], "SOLE", vote, **overrides)
    bundle["decision"] = issue_decision(decision["id"])
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def setup_issued_three_member_decision(votes=None, rdnh_votes=None, **kwargs) -> dict:
    """A three-member case carried through to an ISSUED decision.

    `votes` is a three-element list read in seat order PRESIDING,
    CO_PANELIST_1, CO_PANELIST_2.
    """
    votes = votes or ["TRANSFER", "TRANSFER", "TRANSFER"]
    rdnh_votes = rdnh_votes or [False, False, False]
    bundle = setup_three_member_panel(**kwargs)
    presiding = bundle["panelists"][0]
    decision = draft_decision(bundle["case"]["id"], presiding["id"])
    seats = ["PRESIDING", "CO_PANELIST_1", "CO_PANELIST_2"]
    for panelist, seat, vote, rdnh in zip(bundle["panelists"], seats, votes, rdnh_votes):
        cast_seat_vote(decision["id"], panelist["id"], seat, vote, rdnh_vote=rdnh)
    bundle["decision"] = issue_decision(decision["id"])
    bundle["case"] = read_case(bundle["case"]["id"])
    return bundle


def publish_decision(decision_id: str, redaction_level: str = "NONE", **overrides) -> dict:
    payload = publish_payload(redaction_level, **overrides)
    return get_success_data(api_client.publish_decision(decision_id, payload, PROVIDER_ADMIN))


def precedent_entry_of(decision_id: str) -> dict:
    """A decision's own precedent entry, reported as a list of zero or one row."""
    rows = get_success_data(api_client.get_precedent_entry(decision_id, PROVIDER_ADMIN))
    assert rows, "the decision has no precedent entry"
    return rows[0]


def file_court_challenge(bundle: dict, filed_by: str = "RESPONDENT", **overrides) -> dict:
    payload = court_challenge_payload(filed_by, **overrides)
    if filed_by == "RESPONDENT":
        payload.setdefault("respondent_email", VERIFIED_REGISTRANT_EMAIL)
        headers = make_respondent_headers()
    else:
        headers = make_complainant_headers(bundle["complainant"]["id"])
    return get_success_data(
        api_client.create_court_challenge(bundle["decision"]["id"], payload, headers)
    )


def resolve_court_challenge(challenge_id: str, outcome: str, **overrides) -> dict:
    payload = resolve_challenge_payload(outcome, **overrides)
    return get_success_data(
        api_client.resolve_court_challenge(challenge_id, payload, PROVIDER_ADMIN)
    )


def implement_decision(bundle: dict, **overrides) -> dict:
    payload = {"registrar_action_reference": overrides.pop("registrar_action_reference", "RA-0001")}
    payload.update(overrides)
    return get_success_data(
        api_client.implement_decision(
            bundle["decision"]["id"], payload,
            make_registrar_headers(bundle["registrar"]["id"]),
        )
    )


def issue_deficiency_notice(case_id: str, headers=None, **overrides) -> dict:
    payload = deficiency_notice_payload(**overrides)
    return get_success_data(
        api_client.create_deficiency_notice(case_id, payload, headers or CASE_MANAGER)
    )


def cure_deficiency(case_id: str, notice_id: str, complainant_id: str, notes: str = "Defect cured.") -> dict:
    return get_success_data(
        api_client.create_correction(
            case_id,
            {"notice_id": notice_id, "correction_notes": notes},
            make_complainant_headers(complainant_id),
        )
    )


def withdraw_case(case_id: str, complainant_id: str, reason: str = "Settled privately.") -> dict:
    return get_success_data(
        api_client.withdraw_case(
            case_id, {"reason": reason}, make_complainant_headers(complainant_id)
        )
    )
