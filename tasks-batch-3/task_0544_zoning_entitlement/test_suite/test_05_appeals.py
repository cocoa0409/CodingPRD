"""Appeals: the FILED->UPHELD reversal fork and the appeal-window boundary (PRD §3.6)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    appeal_payload, make_applicant_headers, assert_instant_equals,
    build_decided_approved, set_clock,
)
from test_helpers import api_client as api


# --- UPHELD appeal reverses the approval ----------------------------------

def test_upheld_appeal_moves_application_to_denied_on_appeal(clerk_headers):
    """PRD §3.6: "An UPHELD resolution reverses the approval: it is permitted only while the
    application is in DECIDED_APPROVED (else ERR_INVALID_STATE), moves the appeal to UPHELD,
    and drives the application from DECIDED_APPROVED to DENIED_ON_APPEAL."

    Design: Difficulty/non_linear_state_machine/appeal_fork_upheld_reverses_approval
    """
    ctx = build_decided_approved(app_type="VARIANCE",
                                conditions=[{"condition_code": "COA-1", "condition_text": "Install screening"}])
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    appeal = validate_success(
        api.create_appeal(appeal_payload(app_id), make_applicant_headers(applicant_id)), 201)
    resolved = validate_success(
        api.resolve_appeal(appeal["id"], {"resolution": "UPHELD"}, clerk_headers), 200)
    assert resolved["status"] == "UPHELD", f"appeal must be UPHELD, got {resolved['status']}"
    app = api.get_application(app_id, clerk_headers).json()["data"]
    assert app["status"] == "DENIED_ON_APPEAL", f"application must be DENIED_ON_APPEAL, got {app['status']}"


def test_upheld_appeal_voids_conditions_and_reverts_parcel(clerk_headers):
    """PRD §3.6: "That reversal voids the entitlement's conditions — every ACTIVE condition of
    approval for the application becomes VOIDED — returns the parcel to AVAILABLE, and stamps
    the application's review_window_closed_at with the current clock."

    Design: Difficulty/non_linear_state_machine/appeal_fork_upheld_reverses_approval
    """
    ctx = build_decided_approved(app_type="VARIANCE",
                                conditions=[{"condition_code": "COA-1", "condition_text": "Install screening"}])
    app_id, applicant_id, parcel_id = ctx["app"]["id"], ctx["applicant"]["id"], ctx["parcel"]["id"]
    appeal = validate_success(
        api.create_appeal(appeal_payload(app_id), make_applicant_headers(applicant_id)), 201)
    api.resolve_appeal(appeal["id"], {"resolution": "UPHELD"}, clerk_headers)
    conditions, _ = validate_paginated(api.list_conditions(app_id, clerk_headers))
    assert conditions, "expected at least one condition of approval to have been created"
    assert all(c["status"] == "VOIDED" for c in conditions), \
        f"every ACTIVE condition must become VOIDED, got {[c['status'] for c in conditions]}"
    parcel = api.get_parcel(parcel_id, clerk_headers).json()["data"]
    assert parcel["status"] == "AVAILABLE", f"parcel must revert to AVAILABLE, got {parcel['status']}"


# --- Appeal window boundary (inclusive last instant) ----------------------

def test_appeal_at_exact_deadline_accepted():
    """PRD §3.6: "The filing is valid only when filed_at is on or before the application's
    appeal_deadline (the deadline instant itself is still open); a later filing is rejected
    with ERR_APPEAL_WINDOW_CLOSED."
    PRD §3.6: "A new appeal begins in FILED status."

    Design: Difficulty/boundary_precision_check/appeal_window_inclusive_last_instant
    """
    ctx = build_decided_approved(app_type="VARIANCE")
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    set_clock("2026-06-16T00:00:00Z")  # exactly the appeal_deadline instant
    data = validate_success(
        api.create_appeal(appeal_payload(app_id), make_applicant_headers(applicant_id)), 201)
    assert data["status"] == "FILED", f"appeal at the deadline instant must be FILED, got {data['status']}"


def test_appeal_filed_at_stamped_deadline_instant():
    """PRD §3.6: "Filing captures the application_id under appeal, the appellant_name, and the
    stated grounds, and stamps filed_at with the current clock."
    PRD §3.6: "The filing is valid only when filed_at is on or before the application's
    appeal_deadline (the deadline instant itself is still open)".

    Design: Difficulty/boundary_precision_check/appeal_window_inclusive_last_instant
    """
    ctx = build_decided_approved(app_type="VARIANCE")
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    set_clock("2026-06-16T00:00:00Z")
    data = validate_success(
        api.create_appeal(appeal_payload(app_id), make_applicant_headers(applicant_id)), 201)
    assert_instant_equals(data["filed_at"], "2026-06-16T00:00:00Z", "filed_at (current clock)")


def test_appeal_after_deadline_rejected():
    """PRD §3.6: "The filing is valid only when filed_at is on or before the application's
    appeal_deadline (the deadline instant itself is still open); a later filing is rejected
    with ERR_APPEAL_WINDOW_CLOSED."

    Design: Corner/validations/appeal_after_deadline_returns_window_closed
    """
    ctx = build_decided_approved(app_type="VARIANCE")
    app_id, applicant_id = ctx["app"]["id"], ctx["applicant"]["id"]
    set_clock("2026-06-17T00:00:00Z")  # one day past the 2026-06-16 deadline
    resp = api.create_appeal(appeal_payload(app_id), make_applicant_headers(applicant_id))
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
