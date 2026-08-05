"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and builds all required
preconditions from scratch using only PRD-declared endpoints. The test harness
restarts the server (empty DB, logical clock reset to 2026-05-01T00:00:00Z)
before every test, so nothing is carried over.

Setup calls use get_success_data() so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_franchise_payload,
    create_row_segment_payload,
    create_row_permit_payload,
    create_milestone_payload,
    create_revenue_report_payload,
    create_audit_payload,
    create_complaint_payload,
    create_peg_contribution_payload,
    create_application_payload,
)
from .test_users import (
    TEST_USERS,
    make_authority_headers,
    make_operator_headers,
    make_resident_headers,
)

AUTHORITY = TEST_USERS["authority_headers"]


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance/reset the server logical clock to the given ISO 8601 instant."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, AUTHORITY))


# ----------------------------------------------------------------------
# Tier 1: Franchise state progression
# ----------------------------------------------------------------------
def create_franchise(api, **overrides) -> dict:
    """Create a DRAFT franchise. Returns the franchise."""
    payload = create_franchise_payload(**overrides)
    return get_success_data(api.create_franchise(payload, AUTHORITY))


def create_active_franchise(api, **overrides) -> dict:
    """Create + activate a franchise (lifecycle ACTIVE, version 2). Returns it."""
    fr = create_franchise(api, **overrides)
    return get_success_data(api.activate_franchise(fr["id"], AUTHORITY))


def get_franchise(api, franchise_id) -> dict:
    return get_success_data(api.get_franchise(franchise_id, AUTHORITY))


def get_franchise_version(api, franchise_id) -> int:
    return get_franchise(api, franchise_id)["version"]


# ----------------------------------------------------------------------
# Tier 1: Right-of-way segments and permits
# ----------------------------------------------------------------------
def create_row_segment(api, **overrides) -> dict:
    return get_success_data(api.create_row_segment(create_row_segment_payload(**overrides), AUTHORITY))


def create_requested_permit(api, franchise_id, segment_id, **overrides) -> dict:
    """Operator requests a ROW permit (status REQUESTED)."""
    op = make_operator_headers(franchise_id)
    payload = create_row_permit_payload(franchise_id, segment_id, **overrides)
    return get_success_data(api.create_row_permit(payload, op))


def setup_active_franchise_with_segment(api):
    """ACTIVE franchise + one registered RowSegment. Returns (franchise, segment)."""
    fr = create_active_franchise(api)
    seg = create_row_segment(api)
    return fr, seg


# ----------------------------------------------------------------------
# Tier 1: Build-out milestones
# ----------------------------------------------------------------------
def create_milestone(api, franchise_id, **overrides) -> dict:
    return get_success_data(api.create_milestone(create_milestone_payload(franchise_id, **overrides), AUTHORITY))


def certify_milestone(api, franchise_id, milestone_id, homes_passed) -> dict:
    op = make_operator_headers(franchise_id)
    return get_success_data(api.certify_milestone(milestone_id, {"homes_passed": homes_passed}, op))


# ----------------------------------------------------------------------
# Tier 3: Revenue reports (file -> accept -> pay)
# ----------------------------------------------------------------------
def create_filed_report(api, franchise_id, **overrides) -> dict:
    op = make_operator_headers(franchise_id)
    payload = create_revenue_report_payload(franchise_id, **overrides)
    return get_success_data(api.create_revenue_report(payload, op))


def create_accepted_report(api, franchise_id, **overrides) -> dict:
    rr = create_filed_report(api, franchise_id, **overrides)
    return get_success_data(api.accept_revenue_report(rr["id"], AUTHORITY))


def create_paid_report(api, franchise_id, **overrides) -> dict:
    """File -> accept -> pay the outstanding fee in full. Returns PAID report."""
    rr = create_accepted_report(api, franchise_id, **overrides)
    op = make_operator_headers(franchise_id)
    outstanding = rr["fee_due_cents"] - rr["amount_paid_cents"]
    return get_success_data(api.pay_revenue_report(rr["id"], {"amount_cents": outstanding}, op))


# ----------------------------------------------------------------------
# Tier 3/4: Audits and assessments
# ----------------------------------------------------------------------
def open_audit(api, franchise_id, target_report_id, **overrides) -> dict:
    payload = create_audit_payload(franchise_id, target_report_id, **overrides)
    return get_success_data(api.create_audit(payload, AUTHORITY))


def setup_open_audit_on_paid_report(api, clock="2026-07-09T00:00:00Z"):
    """ACTIVE franchise + report PAID 9169 + clock advanced + OPEN audit on it.

    Returns (franchise, report, audit). The report is UNDER_AUDIT.
    """
    fr = create_active_franchise(api)
    rr = create_paid_report(api, fr["id"])
    set_clock(api, clock)
    au = open_audit(api, fr["id"], rr["id"])
    return fr, rr, au


def finalize_finding(api, audit_id, issuer_user_id="authority-lead",
                     audited=(120010, 50010, 33330)):
    """Finalize an audit with a FINDING and return the created Assessment."""
    payload = {
        "finding": "FINDING",
        "audited_gross_residential_cents": audited[0],
        "audited_gross_commercial_cents": audited[1],
        "audited_gross_advertising_cents": audited[2],
    }
    get_success_data(api.finalize_audit(audit_id, payload, make_authority_headers(issuer_user_id)))
    assessments = get_success_data(api.get_audit_assessments(audit_id, AUTHORITY))
    assert assessments, "Setup step failed: audit finalize FINDING produced no assessment"
    return assessments[0]


def setup_issued_assessment(api, clock="2026-07-09T00:00:00Z", issuer_user_id="authority-lead"):
    """Full chain through a FINDING finalize. Returns (franchise, report, audit, assessment)."""
    fr, rr, au = setup_open_audit_on_paid_report(api, clock=clock)
    assessment = finalize_finding(api, au["id"], issuer_user_id=issuer_user_id)
    return fr, rr, au, assessment


# ----------------------------------------------------------------------
# Tier 1: Complaints
# ----------------------------------------------------------------------
def file_complaint(api, franchise_id, complainant_id="res-1", **overrides) -> dict:
    headers = make_resident_headers(complainant_id)
    payload = create_complaint_payload(franchise_id, **overrides)
    return get_success_data(api.create_complaint(payload, headers))


def resolve_complaint(api, franchise_id, complaint_id, note="Resolved") -> dict:
    op = make_operator_headers(franchise_id)
    return get_success_data(api.resolve_complaint(complaint_id, {"resolution_note": note}, op))


def escalate_complaint(api, complaint_id) -> dict:
    return get_success_data(api.escalate_complaint(complaint_id, AUTHORITY))


# ----------------------------------------------------------------------
# Tier 1: PEG contributions
# ----------------------------------------------------------------------
def record_peg(api, franchise_id, amount_cents=100000, **overrides) -> dict:
    op = make_operator_headers(franchise_id)
    payload = create_peg_contribution_payload(franchise_id, amount_cents=amount_cents, **overrides)
    return get_success_data(api.create_peg_contribution(payload, op))


# ----------------------------------------------------------------------
# Tier 3: Franchise applications
# ----------------------------------------------------------------------
def file_application(api, franchise_id, application_type="TRANSFER",
                     expected_version=None, **overrides) -> dict:
    """File a transfer/renewal application. Reads the current franchise version
    for the OCC token unless expected_version is supplied.
    """
    if expected_version is None:
        expected_version = get_franchise_version(api, franchise_id)
    op = make_operator_headers(franchise_id)
    payload = create_application_payload(
        franchise_id, application_type, expected_version, **overrides
    )
    return get_success_data(api.create_application(payload, op))


def file_transfer_application(api, franchise_id, transferee_name="NewCo", **overrides) -> dict:
    return file_application(
        api, franchise_id, application_type="TRANSFER",
        transferee_name=transferee_name, **overrides
    )


def file_renewal_application(api, franchise_id, proposed_term_end_date="2040-01-01", **overrides) -> dict:
    return file_application(
        api, franchise_id, application_type="RENEWAL",
        proposed_term_end_date=proposed_term_end_date, **overrides
    )


def setup_franchise_in_violation_with_held_app(api):
    """ACTIVE franchise, a SUBMITTED TRANSFER application, then drive the
    franchise IN_VIOLATION via two escalated SERVICE_INTERRUPTION complaints so
    the application is HELD. Returns (franchise, application, [c1, c2]).
    """
    fr = create_active_franchise(api)
    app = file_transfer_application(api, fr["id"], transferee_name="NewCo")
    c1 = file_complaint(api, fr["id"], complainant_id="res-1",
                        category="SERVICE_INTERRUPTION", description="Outage A")
    c2 = file_complaint(api, fr["id"], complainant_id="res-2",
                        category="SERVICE_INTERRUPTION", description="Outage B")
    set_clock(api, "2026-05-03T00:00:00Z")
    escalate_complaint(api, c1["id"])
    escalate_complaint(api, c2["id"])
    return fr, app, [c1, c2]
