"""Hearing scheduling / buffer, and the court-report authoring + revision loop
with its state and temporal gates.

Queue A (Difficulty): non_linear_state_machine (report revision cycle),
cross_entity_state_dependency (submit requires SCHEDULED hearing),
boundary_precision_check (report lead-time inclusive), resource_temporal_overlap
(hearing day-buffer).
Queue B (Corner): invalid-state transitions and hearing/case mismatch.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_case,
    setup_active_volunteer_assigned_case,
    setup_case_with_hearing,
    setup_draft_report,
    setup_submitted_report,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ------------------------- Difficulty: cyclic report revision (SUBMITTED loop)
def test_return_then_revise_returns_to_draft_and_counts_revision(api):
    """PRD 3.6: "A returned report goes back to its author, who revises it,
    advancing RETURNED → DRAFT ... and each revision increments the read-only
    revision_count by one."

    Design: Difficulty/non_linear_state_machine/court_report_revision_cycle
    """
    base = setup_submitted_report(api)
    get_success_data(api.review_report(
        base["report_id"], {"decision": "RETURN", "comments": "add detail"}, base["supervisor_headers"]))
    revised = get_success_data(api.revise_report(
        base["report_id"], {"content_summary": "v2"}, base["volunteer_headers"]))
    assert revised["status"] == "DRAFT"
    assert revised["revision_count"] == 1


def test_report_can_reach_approved_after_revision_loop(api):
    """PRD 3.6: "An approval advances `SUBMITTED → APPROVED`; a return advances
    `SUBMITTED → RETURNED`."

    Design: Difficulty/non_linear_state_machine/court_report_revision_cycle
    """
    base = setup_submitted_report(api)
    get_success_data(api.review_report(
        base["report_id"], {"decision": "RETURN"}, base["supervisor_headers"]))
    get_success_data(api.revise_report(
        base["report_id"], {"content_summary": "v2"}, base["volunteer_headers"]))
    get_success_data(api.submit_report(base["report_id"], base["volunteer_headers"]))
    approved = get_success_data(api.review_report(
        base["report_id"], {"decision": "APPROVE"}, base["supervisor_headers"]))
    assert approved["status"] == "APPROVED"


# ---------------- Difficulty: report submit requires the linked hearing SCHEDULED
def test_submit_report_with_continued_hearing_rejected(api):
    """PRD 3.6: "Submission requires the report to be in `DRAFT` (else
    `ERR_INVALID_STATE`), the linked hearing to still be `SCHEDULED` (else
    `ERR_HEARING_NOT_SCHEDULED`)".

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_hearing_scheduled
    """
    base = setup_draft_report(api)
    get_success_data(api.continue_hearing(base["hearing_id"], base["supervisor_headers"]))
    resp = api.submit_report(base["report_id"], base["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_HEARING_NOT_SCHEDULED.value)


def test_submit_report_with_continued_hearing_leaves_draft(api):
    """PRD 3.6: "Submission requires the report to be in `DRAFT` (else
    `ERR_INVALID_STATE`), the linked hearing to still be `SCHEDULED` (else
    `ERR_HEARING_NOT_SCHEDULED`)".

    Design: Difficulty/cross_entity_state_dependency/report_submit_requires_hearing_scheduled
    """
    base = setup_draft_report(api)
    get_success_data(api.continue_hearing(base["hearing_id"], base["supervisor_headers"]))
    api.submit_report(base["report_id"], base["volunteer_headers"])
    after = get_success_data(api.get_court_report(base["report_id"], base["supervisor_headers"]))
    assert after["status"] == "DRAFT", "a rejected submit must leave the report in DRAFT"


# ------------------- Difficulty: report lead-time inclusive-boundary (now == due)
def test_submit_report_at_exactly_due_instant_allowed(api):
    """PRD 3.6: "the filing deadline to be intact — the logical clock must be at or
    before scheduled_at minus 3 days, meaning the report is submitted at least 3
    days before the hearing; a later submission fails with
    ERR_REPORT_DEADLINE_PASSED. The boundary is inclusive: submitting at exactly
    the due instant is allowed."

    Design: Difficulty/boundary_precision_check/report_lead_time_inclusive_boundary
    """
    base = setup_draft_report(api, scheduled_at="2026-07-20T09:00:00Z")
    set_clock(api, "2026-07-17T09:00:00Z")  # exactly scheduled_at - 3 days
    resp = api.submit_report(base["report_id"], base["volunteer_headers"])
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "SUBMITTED"


def test_submit_report_one_second_past_due_rejected(api):
    """PRD 3.6: "a later submission fails with ERR_REPORT_DEADLINE_PASSED. The
    boundary is inclusive: submitting at exactly the due instant is allowed."

    Design: Difficulty/boundary_precision_check/report_lead_time_inclusive_boundary
    """
    base = setup_draft_report(api, scheduled_at="2026-07-20T09:00:00Z")
    set_clock(api, "2026-07-17T09:00:01Z")  # one second past the due instant
    resp = api.submit_report(base["report_id"], base["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_REPORT_DEADLINE_PASSED.value)


# --------------------------- Difficulty: per-case hearing day-buffer conflict
def test_hearing_within_buffer_rejected(api):
    """PRD 3.5: "a new hearing is rejected with `ERR_HEARING_BUFFER_CONFLICT` if
    the absolute gap between the new `scheduled_at` and any existing scheduled
    hearing's `scheduled_at` is less than 7 days."

    Design: Difficulty/resource_temporal_overlap/hearing_day_buffer_conflict_on_case
    """
    base = setup_case_with_hearing(api, scheduled_at="2026-07-20T09:00:00Z")
    resp = api.create_hearing(base["case_id"], {
        "hearing_type": "REVIEW", "scheduled_at": "2026-07-24T09:00:00Z"}, base["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_HEARING_BUFFER_CONFLICT.value)


def test_hearing_exactly_buffer_apart_allowed(api):
    """PRD 3.5: "Exactly 7 days apart is allowed, and hearings that are `HELD`,
    `CONTINUED`, or `CANCELLED` no longer occupy the calendar."

    Design: Difficulty/resource_temporal_overlap/hearing_day_buffer_conflict_on_case
    """
    base = setup_case_with_hearing(api, scheduled_at="2026-07-20T09:00:00Z")
    resp = api.create_hearing(base["case_id"], {
        "hearing_type": "REVIEW", "scheduled_at": "2026-07-27T09:00:00Z"}, base["supervisor_headers"])
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ------------------------------------------- Corner: invalid-state transitions
def test_file_draft_report_rejected_invalid_state(api):
    """PRD 3.6: "An approved report is filed with the court by the case's
    supervisor, advancing APPROVED → FILED, which likewise requires the report be
    APPROVED and the actor be the case's supervisor."
    PRD 2.10: "State — the target and related resources are in a state that
    permits the operation, else ERR_INVALID_STATE, ERR_CASE_CLOSED,
    ERR_HEARING_NOT_SCHEDULED, or ERR_VOLUNTEER_NOT_ACTIVE (409)."

    Design: Corner/state_machines/file_report_from_draft_returns_invalid_state
    """
    base = setup_draft_report(api)
    resp = api.file_report(base["report_id"], base["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_hold_cancelled_hearing_rejected_invalid_state(api):
    """PRD 3.5: "A scheduled hearing is resolved by the supervisor into one of
    three terminal states: holding it moves SCHEDULED → HELD, continuing
    (postponing) it moves SCHEDULED → CONTINUED, and cancelling it moves SCHEDULED
    → CANCELLED. Each requires the hearing to be SCHEDULED, otherwise
    ERR_INVALID_STATE."

    Design: Corner/state_machines/hold_cancelled_hearing_returns_invalid_state
    """
    base = setup_case_with_hearing(api)
    get_success_data(api.cancel_hearing(base["hearing_id"], base["supervisor_headers"]))
    resp = api.hold_hearing(base["hearing_id"], base["supervisor_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_court_report_hearing_from_other_case_rejected(api):
    """PRD 3.6: "The referenced hearing must belong to the report's own case, else
    ERR_HEARING_CASE_MISMATCH."

    Design: Corner/errors/report_hearing_case_mismatch_returns_409
    """
    base = setup_active_volunteer_assigned_case(api)
    c2 = create_case(api, base["supervisor_id"], child_initials="K.K.")
    h2 = get_success_data(api.create_hearing(
        c2["id"], {"hearing_type": "STATUS", "scheduled_at": "2026-07-20T09:00:00Z"},
        base["supervisor_headers"]))
    resp = api.create_court_report(
        base["case_id"], {"hearing_id": h2["id"], "content_summary": "s", "recommendation": "r"},
        base["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_HEARING_CASE_MISMATCH.value)
