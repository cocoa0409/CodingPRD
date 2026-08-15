"""Composite setup helpers.

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data() so a
setup failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_BOOKING_DATE, REQUIRED_DOC_TYPES
from .factories import (
    create_aircraft_payload,
    create_default_case_payload,
    create_document_payload,
    create_inspector_payload,
    create_lease_payload,
    create_lessee_payload,
    create_novation_request_payload,
    create_reserve_claim_payload,
    create_utilization_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_credit_officer_headers,
    make_legal_approver_headers,
    make_lessee_rep_headers,
    make_tech_inspector_headers,
)

ADMIN = TEST_USERS["lessor_admin_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def _ok(resp, what: str):
    assert resp.status_code < 300, (
        f"Setup failed: {what} -> HTTP {resp.status_code}: {resp.text}"
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_aircraft(**overrides):
    """Register an aircraft. Returns the aircraft dict."""
    return _ok(api_client.create_aircraft(create_aircraft_payload(**overrides), ADMIN),
               "create aircraft")


def create_lessee(**overrides):
    """Register a lessee. Returns the lessee dict."""
    return _ok(api_client.create_lessee(create_lessee_payload(**overrides), ADMIN),
               "create lessee")


def create_inspector(**overrides):
    """Register an inspector. Returns the inspector dict."""
    return _ok(api_client.create_inspector(create_inspector_payload(**overrides), ADMIN),
               "create inspector")


def add_verified_document(aircraft_id: str, doc_type: str, doc_reference: str = None):
    """Submit + verify one document of the given type. Returns the document."""
    payload = create_document_payload(doc_type=doc_type)
    if doc_reference is not None:
        payload["doc_reference"] = doc_reference
    doc = _ok(api_client.create_document(aircraft_id, payload, ADMIN),
              f"submit document {doc_type}")
    return _ok(api_client.review_document(doc["id"], {"decision": "VERIFIED"}, ADMIN),
               f"verify document {doc_type}")


def create_aircraft_with_birth_record(**aircraft_overrides):
    """Aircraft with one VERIFIED BIRTH_RECORD (the activation safety gate).

    Returns (aircraft, birth_record_document)."""
    aircraft = create_aircraft(**aircraft_overrides)
    doc = add_verified_document(aircraft["id"], "BIRTH_RECORD")
    return aircraft, doc


def create_aircraft_with_full_records(**aircraft_overrides):
    """Aircraft with all four required doc types VERIFIED.

    Returns (aircraft, documents_by_type)."""
    aircraft = create_aircraft(**aircraft_overrides)
    docs = {dt: add_verified_document(aircraft["id"], dt) for dt in REQUIRED_DOC_TYPES}
    return aircraft, docs


# ---------------------------------------------------------------------------
# Tier 2: leases and activation
# ---------------------------------------------------------------------------

def create_draft_lease(aircraft_id: str = None, lessee_id: str = None, **overrides):
    """Create a DRAFT lease (creating its aircraft/lessee when not supplied).

    Returns (lease, aircraft, lessee)."""
    aircraft = create_aircraft_with_birth_record()[0] if aircraft_id is None else None
    ac_id = aircraft_id if aircraft_id is not None else aircraft["id"]
    lessee = create_lessee() if lessee_id is None else None
    ls_id = lessee_id if lessee_id is not None else lessee["id"]
    payload = create_lease_payload(aircraft_id=ac_id, lessee_id=ls_id, **overrides)
    lease = _ok(api_client.create_lease(payload, ADMIN), "create lease")
    return lease, aircraft, lessee


def create_active_lease(**overrides):
    """DRAFT lease walked to ACTIVE (aircraft flipped to ON_LEASE).

    Keyword args are forwarded to the lease payload. To reuse a pre-built
    aircraft (e.g. one with full records) pass ``aircraft=...``.

    Returns (lease, aircraft, lessee)."""
    aircraft = overrides.pop("aircraft", None)
    lessee = overrides.pop("lessee", None)
    ac_id = aircraft["id"] if aircraft is not None else None
    ls_id = lessee["id"] if lessee is not None else None
    lease, aircraft, lessee = create_draft_lease(ac_id, ls_id, **overrides)
    lease = _ok(api_client.activate_lease(lease["id"], ADMIN), "activate lease")
    if aircraft is None:
        aircraft = _ok(api_client.get_aircraft(lease["aircraft_id"], ADMIN), "fetch aircraft")
    return lease, aircraft, lessee


# ---------------------------------------------------------------------------
# Tier 3: utilization reports and reserve claims
# ---------------------------------------------------------------------------

def submit_report(lease_id: str, lessee_id: str, **overrides):
    """LesseeRep submits a utilization report on its own lease."""
    payload = create_utilization_report_payload(**overrides)
    return _ok(
        api_client.create_utilization_report(
            lease_id, payload, make_lessee_rep_headers(lessee_id)),
        "submit utilization report")


def submit_and_accept_report(lease_id: str, lessee_id: str, **overrides):
    """Submit a utilization report and have the lessor ACCEPT it."""
    report = submit_report(lease_id, lessee_id, **overrides)
    return _ok(
        api_client.review_utilization_report(report["id"], {"decision": "ACCEPT"}, ADMIN),
        "accept utilization report")


def create_lease_with_accepted_report(report_overrides: dict = None, **lease_overrides):
    """ACTIVE lease with one ACCEPTED utilization report.

    Returns (lease, aircraft, lessee, report)."""
    lease, aircraft, lessee = create_active_lease(**lease_overrides)
    report = submit_and_accept_report(lease["id"], lessee["id"], **(report_overrides or {}))
    lease = _ok(api_client.get_lease(lease["id"], ADMIN), "re-read lease after accept")
    return lease, aircraft, lessee, report


def create_approved_claim(lease_id: str, lessee_id: str, amount_cents: int, **overrides):
    """File a reserve claim and have the lessor approve it for amount_cents."""
    payload = create_reserve_claim_payload(claimed_amount_cents=amount_cents, **overrides)
    claim = _ok(
        api_client.create_reserve_claim(lease_id, payload, make_lessee_rep_headers(lessee_id)),
        "file reserve claim")
    return _ok(
        api_client.decide_reserve_claim(
            claim["id"], {"decision": "APPROVE", "approved_amount_cents": amount_cents}, ADMIN),
        "approve reserve claim")


def create_paid_claim(lease_id: str, lessee_id: str, amount_cents: int, **overrides):
    """Approved claim paid by finance."""
    claim = create_approved_claim(lease_id, lessee_id, amount_cents, **overrides)
    return _ok(api_client.pay_reserve_claim(claim["id"], FINANCE), "pay reserve claim")


# ---------------------------------------------------------------------------
# Tier 4: return-case workflow
# ---------------------------------------------------------------------------

def _get_open_return_case(lease_id: str):
    cases, _meta = _list(api_client.list_return_cases(lease_id, ADMIN))
    assert cases, "Setup failed: no return case found after initiate-return"
    return cases[0]


def _list(resp):
    assert resp.status_code == 200, (
        f"Setup failed: list call -> HTTP {resp.status_code}: {resp.text}"
    )
    return validate_paginated(resp)


def create_lease_with_return_initiated(aircraft=None, **lease_overrides):
    """ACTIVE lease with return initiated: ReturnCase OPEN, 4 PENDING items.

    Returns (lease, aircraft, lessee, return_case)."""
    lease, aircraft, lessee = create_active_lease(aircraft=aircraft, **lease_overrides)
    lease = _ok(api_client.initiate_return(lease["id"], ADMIN), "initiate return")
    rc = _get_open_return_case(lease["id"])
    return lease, aircraft, lessee, rc


def get_checklist_items(return_case_id: str):
    """Return the case's checklist items keyed by item_code."""
    items, _meta = _list(api_client.list_checklist_items(return_case_id, ADMIN))
    assert len(items) == 4, f"Setup failed: expected 4 checklist items, got {len(items)}"
    return {item["item_code"]: item for item in items}


def advance_return_case(return_case_id: str, to: str):
    return _ok(api_client.advance_return_case(return_case_id, {"to": to}, ADMIN),
               f"advance return case to {to}")


def book_inspector(return_case_id: str, inspector_id: str, booking_date: str = DEFAULT_BOOKING_DATE):
    """Book an inspector for a return case on a date (default: clock default)."""
    return _ok(
        api_client.create_inspection_booking(
            return_case_id,
            {"inspector_id": inspector_id, "booking_date": booking_date},
            ADMIN),
        "book inspector")


def create_return_case_in_inspection(**lease_overrides):
    """ReturnCase walked OPEN -> RECORDS_VERIFIED -> INSPECTION, with an
    inspector booked on the logical clock's default date.

    Returns (lease, aircraft, lessee, return_case, inspector)."""
    aircraft, _docs = create_aircraft_with_full_records()
    lease, aircraft, lessee, rc = create_lease_with_return_initiated(aircraft=aircraft, **lease_overrides)
    rc = advance_return_case(rc["id"], "RECORDS_VERIFIED")
    rc = advance_return_case(rc["id"], "INSPECTION")
    inspector = create_inspector()
    book_inspector(rc["id"], inspector["id"])
    return lease, aircraft, lessee, rc, inspector


def inspect_item(item_id: str, inspector_id: str, outcome: str,
                 estimate_cents: int = None):
    """Booked inspector records an outcome on a checklist item."""
    payload = {"outcome": outcome}
    if estimate_cents is not None:
        payload["rectification_cost_estimate_cents"] = estimate_cents
    return _ok(
        api_client.inspect_checklist_item(item_id, payload, make_tech_inspector_headers(inspector_id)),
        f"inspect item {outcome}")


def create_return_case_in_negotiation(non_compliant: dict = None, **lease_overrides):
    """ReturnCase walked into NEGOTIATION.

    ``non_compliant`` maps item_code -> rectification estimate cents; every
    other item is inspected COMPLIANT. Default: ENGINE NON_COMPLIANT at 80000.

    Returns (lease, aircraft, lessee, return_case, inspector)."""
    non_compliant = {"ENGINE": 80000} if non_compliant is None else non_compliant
    lease, aircraft, lessee, rc, inspector = create_return_case_in_inspection(**lease_overrides)
    items = get_checklist_items(rc["id"])
    for code, item in items.items():
        if code in non_compliant:
            inspect_item(item["id"], inspector["id"], "NON_COMPLIANT", non_compliant[code])
        else:
            inspect_item(item["id"], inspector["id"], "COMPLIANT")
    rc = advance_return_case(rc["id"], "NEGOTIATION")
    return lease, aircraft, lessee, rc, inspector


def create_return_case_agreed(proposal_cents: int, non_compliant: dict = None,
                              reserve_report: dict = None, paid_claim_cents: int = None,
                              **lease_overrides):
    """ReturnCase walked into AGREED with a LESSOR proposal of proposal_cents
    standing, accepted by the lessee.

    Optionally pre-loads the reserve ledger: ``reserve_report`` (forwarded to
    the utilization-report factory, which is then accepted) and
    ``paid_claim_cents`` (approved and paid).

    Returns (lease, aircraft, lessee, return_case, inspector)."""
    lease, aircraft, lessee = create_active_lease(**lease_overrides)
    if reserve_report is not None:
        submit_and_accept_report(lease["id"], lessee["id"], **reserve_report)
    if paid_claim_cents is not None:
        create_paid_claim(lease["id"], lessee["id"], paid_claim_cents)
    # Upgrade the airframe to full records for the records gate.
    ac_id = lease["aircraft_id"]
    for dt in REQUIRED_DOC_TYPES:
        if dt != "BIRTH_RECORD":
            add_verified_document(ac_id, dt)
    lease = _ok(api_client.initiate_return(lease["id"], ADMIN), "initiate return")
    rc = _get_open_return_case(lease["id"])
    rc = advance_return_case(rc["id"], "RECORDS_VERIFIED")
    rc = advance_return_case(rc["id"], "INSPECTION")
    inspector = create_inspector()
    book_inspector(rc["id"], inspector["id"])
    non_compliant = {"ENGINE": 80000} if non_compliant is None else non_compliant
    items = get_checklist_items(rc["id"])
    for code, item in items.items():
        if code in non_compliant:
            inspect_item(item["id"], inspector["id"], "NON_COMPLIANT", non_compliant[code])
        else:
            inspect_item(item["id"], inspector["id"], "COMPLIANT")
    rc = advance_return_case(rc["id"], "NEGOTIATION")
    rc = _ok(api_client.create_proposal(rc["id"], {"amount_cents": proposal_cents}, ADMIN),
             "lessor proposal")
    rc = _ok(
        api_client.agree_return_case(
            rc["id"],
            {"expected_return_case_version": rc["version"]},
            make_lessee_rep_headers(lessee["id"])),
        "lessee agree")
    return lease, aircraft, lessee, rc, inspector


# ---------------------------------------------------------------------------
# Tier 5: defaults and repossession
# ---------------------------------------------------------------------------

def create_default_case(lease_id: str, declared_by: str = "cred_1", **overrides):
    """CreditOfficer declares default on the lease (lease -> DEFAULTED)."""
    payload = create_default_case_payload(**overrides)
    return _ok(
        api_client.create_default_case(lease_id, payload, make_credit_officer_headers(declared_by)),
        "declare default")


def create_authorized_default_case(lease_id: str, declared_by: str = "cred_1",
                                   authorizer: str = "legal_1",
                                   advance_clock_to: str = "2026-09-01T00:00:00Z",
                                   **overrides):
    """Default case declared, clock advanced past the cure deadline, and
    repossession authorized by a distinct legal approver."""
    case = create_default_case(lease_id, declared_by=declared_by, **overrides)
    if advance_clock_to is not None:
        _ok(api_client.set_clock({"to_iso8601": advance_clock_to}, ADMIN), "advance clock")
    case = _ok(
        api_client.authorize_repossession(case["id"], make_legal_approver_headers(authorizer)),
        "authorize repossession")
    return case


# ---------------------------------------------------------------------------
# Novation
# ---------------------------------------------------------------------------

def create_credit_approved_novation(lease_id: str, lessee_id: str, proposed_lessee_id: str,
                                    request_type: str = "NOVATION",
                                    credit_officer: str = "cred_1"):
    """Lessee files a novation/sublease request; CreditOfficer approves the
    credit stage. Returns the CREDIT_APPROVED request."""
    payload = create_novation_request_payload(
        request_type=request_type, proposed_lessee_id=proposed_lessee_id)
    req = _ok(
        api_client.create_novation_request(
            lease_id, payload, make_lessee_rep_headers(lessee_id)),
        "file novation request")
    return _ok(
        api_client.review_novation_request(
            req["id"], {"decision": "APPROVE"}, make_credit_officer_headers(credit_officer)),
        "credit-approve novation request")
