"""Permit approval gates, issuance scheduling, and driller-log validation.

Covers the safety-before-fiscal and state-before-referential precedence pairs,
the cross-entity permit-issued dependency, the buffered half-open driller
schedule overlap, plus the related corner-queue permit/driller-log claims.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_applicant_headers, make_driller_headers,
    factories as f, fixtures as fx,
)

OFFICER = TEST_USERS["health_officer_headers"]


def _issue_permit_with_window(api, *, scheduled_start, scheduled_end,
                              driller_id=None, applicant_id=None, aquifer_id=None,
                              issue=True):
    """Build a paid+approved permit (optionally issued) on a fresh well using
    the supplied window. Reuses the given driller/applicant/aquifer when passed
    so the same driller can hold several permits."""
    if aquifer_id is None:
        aquifer_id = fx.create_aquifer(api)["id"]
    if applicant_id is None:
        applicant_id = fx.create_applicant(api)["id"]
    if driller_id is None:
        driller_id = fx.create_driller(api)["id"]
    well = fx.create_well(api, applicant_id, aquifer_id)
    permit = fx.create_submitted_permit(
        api, well["id"], applicant_id, driller_id,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end)
    fx.pay_permit(api, permit["id"], applicant_id)
    fx.approve_permit(api, permit["id"])
    if issue:
        fx.issue_permit(api, permit["id"])
    return {"aquifer_id": aquifer_id, "applicant_id": applicant_id,
            "driller_id": driller_id, "well_id": well["id"], "permit_id": permit["id"]}


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / approve_safety_precedes_fiscal
# --------------------------------------------------------------------------
def test_approve_reports_setback_violation_over_unpaid_fee(api):
    """PRD §3.2: "Because safety precedes fiscal, a permit that violates setbacks
    and is also unpaid surfaces the setback violation, not the unpaid fee."

    Design: Difficulty/priority_pair_validation_conflict/approve_safety_precedes_fiscal
    """
    ctx = fx.setup_submitted_permit(
        api, min_setback_septic_ft=100, setback_septic_ft=50,
        min_setback_property_line_ft=10, setback_property_line_ft=15)
    resp = api.approve_permit(ctx.permit_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_SETBACK_VIOLATION)


def test_approve_setback_violation_on_property_line_precedes_fee(api):
    """PRD §3.2: "The setback check requires that the measured septic setback is
    at least the aquifer's min_setback_septic_ft and that the measured
    property-line setback is at least the aquifer's min_setback_property_line_ft;
    if either falls short, approval is rejected with ERR_SETBACK_VIOLATION (HTTP
    422)."

    Design: Difficulty/priority_pair_validation_conflict/approve_safety_precedes_fiscal
    """
    ctx = fx.setup_submitted_permit(
        api, min_setback_septic_ft=50, setback_septic_ft=60,
        min_setback_property_line_ft=20, setback_property_line_ft=15)
    resp = api.approve_permit(ctx.permit_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_SETBACK_VIOLATION)


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / driller_log_state_precedes_referential
# --------------------------------------------------------------------------
def test_driller_log_state_check_precedes_assignment_check(api):
    """PRD §2.9: "then existence of every referenced resource (the
    ERR_*_NOT_FOUND family); then state validity for the requested transition
    (the generic ERR_INVALID_STATE and its endpoint-specific siblings)".
    PRD §3.3: "The referenced permit must be in ISSUED status; a log against a
    permit in any other status is rejected with ERR_PERMIT_NOT_ISSUED (HTTP
    409)."

    Design: Difficulty/priority_pair_validation_conflict/driller_log_state_precedes_referential
    """
    ctx = fx.setup_submitted_permit(api)
    fx.pay_permit(api, ctx.permit_id, ctx.applicant_id)
    fx.approve_permit(api, ctx.permit_id)  # APPROVED, NOT issued
    other_driller = fx.create_driller(api)
    payload = f.driller_log_payload(ctx.permit_id, other_driller["id"], total_depth_ft=300)
    resp = api.create_driller_log(payload, make_driller_headers(other_driller["id"]))
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)


def test_driller_log_state_precedence_leaves_permit_unchanged(api):
    """PRD §2.9: "the checks are applied in a fixed priority order and the first
    failing check determines the response."
    PRD §3.3: "The referenced permit must be in ISSUED status; a log against a
    permit in any other status is rejected with ERR_PERMIT_NOT_ISSUED (HTTP
    409)."

    Design: Difficulty/priority_pair_validation_conflict/driller_log_state_precedes_referential
    """
    ctx = fx.setup_submitted_permit(api)
    fx.pay_permit(api, ctx.permit_id, ctx.applicant_id)
    fx.approve_permit(api, ctx.permit_id)
    other_driller = fx.create_driller(api)
    payload = f.driller_log_payload(ctx.permit_id, other_driller["id"], total_depth_ft=300)
    api.create_driller_log(payload, make_driller_headers(other_driller["id"]))
    permit = get_success_data(api.get_construction_permit(ctx.permit_id, OFFICER))
    assert permit["status"] == "APPROVED"


# --------------------------------------------------------------------------
# cross_entity_state_dependency / driller_log_requires_permit_issued
# --------------------------------------------------------------------------
def test_driller_log_against_approved_permit_rejected(api):
    """PRD §3.3: "The referenced permit must be in ISSUED status; a log against a
    permit in any other status is rejected with ERR_PERMIT_NOT_ISSUED (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/driller_log_requires_permit_issued
    """
    ctx = fx.setup_submitted_permit(api)
    fx.pay_permit(api, ctx.permit_id, ctx.applicant_id)
    fx.approve_permit(api, ctx.permit_id)
    payload = f.driller_log_payload(ctx.permit_id, ctx.driller_id, total_depth_ft=300)
    resp = api.create_driller_log(payload, ctx.driller_headers)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)


def test_driller_log_against_submitted_permit_rejected(api):
    """PRD §3.3: "The referenced permit must be in ISSUED status; a log against a
    permit in any other status is rejected with ERR_PERMIT_NOT_ISSUED (HTTP
    409)."

    Design: Difficulty/cross_entity_state_dependency/driller_log_requires_permit_issued
    """
    ctx = fx.setup_submitted_permit(api)  # still SUBMITTED
    payload = f.driller_log_payload(ctx.permit_id, ctx.driller_id, total_depth_ft=300)
    resp = api.create_driller_log(payload, ctx.driller_headers)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ISSUED)


# --------------------------------------------------------------------------
# resource_temporal_overlap / driller_schedule_buffered_halfopen_overlap
# --------------------------------------------------------------------------
def test_issue_rejected_when_buffered_window_overlaps(api):
    """PRD §3.2: "the assigned driller must have no other permit in ISSUED or
    COMPLETED status whose scheduled window, when each side is expanded by the
    travel buffer DRILL_TRAVEL_BUFFER_HOURS (4 hours), overlaps this permit's
    scheduled window; the windows are treated as half-open on [scheduled_start,
    scheduled_end). A conflict is rejected with ERR_DRILLER_SCHEDULE_CONFLICT
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/driller_schedule_buffered_halfopen_overlap
    """
    first = _issue_permit_with_window(
        api, scheduled_start="2026-05-10T08:00:00Z", scheduled_end="2026-05-11T17:00:00Z",
        issue=True)
    second = _issue_permit_with_window(
        api, scheduled_start="2026-05-11T20:00:00Z", scheduled_end="2026-05-12T10:00:00Z",
        driller_id=first["driller_id"], applicant_id=first["applicant_id"],
        aquifer_id=first["aquifer_id"], issue=False)
    resp = api.issue_permit(second["permit_id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_DRILLER_SCHEDULE_CONFLICT)


def test_issue_succeeds_when_windows_clear_the_buffer(api):
    """PRD §3.2: "the assigned driller must have no other permit in ISSUED or
    COMPLETED status whose scheduled window, when each side is expanded by the
    travel buffer DRILL_TRAVEL_BUFFER_HOURS (4 hours), overlaps this permit's
    scheduled window; the windows are treated as half-open on [scheduled_start,
    scheduled_end)."

    Design: Difficulty/resource_temporal_overlap/driller_schedule_buffered_halfopen_overlap
    """
    first = _issue_permit_with_window(
        api, scheduled_start="2026-05-10T08:00:00Z", scheduled_end="2026-05-11T17:00:00Z",
        issue=True)
    second = _issue_permit_with_window(
        api, scheduled_start="2026-05-12T02:00:00Z", scheduled_end="2026-05-12T12:00:00Z",
        driller_id=first["driller_id"], applicant_id=first["applicant_id"],
        aquifer_id=first["aquifer_id"], issue=False)
    resp = api.issue_permit(second["permit_id"], OFFICER)
    permit = validate_success(resp, 200)
    assert permit["status"] == "ISSUED"


# --------------------------------------------------------------------------
# Corner: state_machines, validations, endpoints
# --------------------------------------------------------------------------
def test_approve_denied_permit_returns_invalid_state(api):
    """PRD §3.2: "A successful approval moves the permit from SUBMITTED to
    APPROVED."
    PRD §2.9: "then state validity for the requested transition (the generic
    ERR_INVALID_STATE and its endpoint-specific siblings)".

    Design: Corner/state_machines/approve_already_denied_permit_returns_invalid_state
    """
    ctx = fx.setup_submitted_permit(api)
    get_success_data(api.deny_permit(ctx.permit_id, OFFICER))
    resp = api.approve_permit(ctx.permit_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_driller_log_with_suspended_driller_rejected(api):
    """PRD §3.3: "the driller's status must be ACTIVE and the completion instant
    must fall strictly before the driller's license_expires_on; a suspended or
    lapsed license is rejected with ERR_DRILLER_LICENSE_INVALID (HTTP 422)."

    Design: Corner/state_machines/driller_log_with_suspended_driller_returns_license_invalid
    """
    ctx = fx.setup_submitted_permit(api)
    fx.pay_permit(api, ctx.permit_id, ctx.applicant_id)
    fx.approve_permit(api, ctx.permit_id)
    fx.issue_permit(api, ctx.permit_id)
    get_success_data(api.suspend_driller(ctx.driller_id, OFFICER))
    payload = f.driller_log_payload(ctx.permit_id, ctx.driller_id, total_depth_ft=300,
                                    grout_type="CEMENT")
    resp = api.create_driller_log(payload, ctx.driller_headers)
    validate_error(resp, ApiErrorId.ERR_DRILLER_LICENSE_INVALID)


def test_driller_log_wrong_driller_on_issued_permit_rejected(api):
    """PRD §3.3: "The filing driller must be the one assigned to the permit — the
    log's driller_id must equal the permit's assigned driller — otherwise the
    filing is rejected with ERR_DRILLER_NOT_ASSIGNED (HTTP 409)."

    Design: Corner/validations/driller_log_wrong_driller_on_issued_permit_returns_not_assigned
    """
    ctx = fx.setup_submitted_permit(api)
    fx.pay_permit(api, ctx.permit_id, ctx.applicant_id)
    fx.approve_permit(api, ctx.permit_id)
    fx.issue_permit(api, ctx.permit_id)
    other_driller = fx.create_driller(api)
    payload = f.driller_log_payload(ctx.permit_id, other_driller["id"], total_depth_ft=300)
    resp = api.create_driller_log(payload, make_driller_headers(other_driller["id"]))
    validate_error(resp, ApiErrorId.ERR_DRILLER_NOT_ASSIGNED)


def test_approve_unpaid_permit_with_valid_setback_returns_fee_unpaid(api):
    """PRD §3.2: "Only if the setbacks pass does the officer's approval then
    require that the fee has been paid; an unpaid permit is rejected with
    ERR_FEE_UNPAID (HTTP 402)."

    Design: Corner/validations/approve_unpaid_permit_with_valid_setback_returns_fee_unpaid
    """
    ctx = fx.setup_submitted_permit(
        api, min_setback_septic_ft=50, setback_septic_ft=60,
        min_setback_property_line_ft=10, setback_property_line_ft=15)
    resp = api.approve_permit(ctx.permit_id, OFFICER)
    validate_error(resp, ApiErrorId.ERR_FEE_UNPAID)


def test_permit_applicant_mismatch_rejected(api):
    """PRD §3.2: "the applicant_id (which must equal the well's owning applicant
    — a mismatch is rejected with ERR_APPLICANT_MISMATCH, HTTP 409)".

    Design: Corner/validations/permit_applicant_mismatch_returns_error
    """
    aquifer = fx.create_aquifer(api, sensitivity="LOW")
    owner_a = fx.create_applicant(api)
    owner_b = fx.create_applicant(api)
    driller = fx.create_driller(api)
    well = fx.create_well(api, owner_a["id"], aquifer["id"])
    payload = f.construction_permit_payload(well["id"], owner_b["id"], driller["id"])
    resp = api.create_construction_permit(payload, make_applicant_headers(owner_b["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICANT_MISMATCH)


def test_list_permits_filtered_by_well(api):
    """PRD §2.3: the meta block reports total_count, "the number of records
    matching the filter before pagination" — so the construction-permit list
    endpoint returns the permits matching a well filter.

    Design: Corner/endpoints/fk_reverse_permits_by_well_filtered_list
    """
    ctx = fx.setup_submitted_permit(api)
    resp = api.list_construction_permits(OFFICER, params={"well_id": ctx.well_id})
    body = resp.json()
    ids = [p["id"] for p in body["data"]]
    assert ctx.permit_id in ids


def test_expiry_sweep_expires_issued_permit(api):
    """PRD §3.10: "Any construction permit in ISSUED status whose expires_on is
    at or before the current instant is moved to EXPIRED."

    Design: Corner/endpoints/expiry_sweep_expires_issued_permit
    """
    ctx = fx.setup_submitted_permit(api)
    fx.pay_permit(api, ctx.permit_id, ctx.applicant_id)
    fx.approve_permit(api, ctx.permit_id)
    fx.issue_permit(api, ctx.permit_id)
    get_success_data(api.set_clock({"to_iso8601": "2027-06-01T00:00:00Z"}, OFFICER))
    get_success_data(api.expiry_sweep(OFFICER))
    permit = get_success_data(api.get_construction_permit(ctx.permit_id, OFFICER))
    assert permit["status"] == "EXPIRED"
