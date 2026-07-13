"""Visit scheduling: the reschedule cycle, nurse double-booking with travel buffer,
duplicate-target-date, the schedule-window check, enrollment-active gating on
completion, and enrollment-filtered listing."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_visit_payload,
    complete_visit_payload,
    reschedule_visit_payload,
    create_nurse,
    make_nurse_headers,
    schedule_visit,
    setup_active_enrollment,
    setup_enrolled_enrollment,
    setup_shared_nurse_enrollments,
)


# ─── Difficulty: reschedule cycle ───────────────────────
def _reschedule_chain():
    """Active enrollment with v1, rescheduled to v2, rescheduled again to v3.
    Returns (ctx, v1, v2, v3)."""
    ctx = setup_active_enrollment()
    v1 = schedule_visit(
        ctx, target_date="2026-06-05",
        scheduled_start="2026-06-05T09:00:00Z", scheduled_end="2026-06-05T10:00:00Z",
    )
    from test_helpers import get_success_data, api_client
    v2 = get_success_data(api_client.reschedule_visit(
        v1["id"],
        reschedule_visit_payload("2026-06-06", "2026-06-06T09:00:00Z", "2026-06-06T10:00:00Z"),
        ctx.nurse_headers,
    ))
    v3 = get_success_data(api_client.reschedule_visit(
        v2["id"],
        reschedule_visit_payload("2026-06-07", "2026-06-07T09:00:00Z", "2026-06-07T10:00:00Z"),
        ctx.nurse_headers,
    ))
    return ctx, v1, v2, v3


def test_reschedule_twice_leaves_two_rescheduled_and_one_scheduled(api):
    """PRD 3.5: "Rescheduling is a nurse action, permitted only by the visit's owning
    nurse (X-User-ID must equal the visit's nurse_id, else ERR_NOT_VISIT_OWNER), that
    moves a SCHEDULED visit to RESCHEDULED and, in the same operation, creates and
    returns a replacement visit in SCHEDULED status."
    PRD 3.5: "Because the replacement is itself SCHEDULED, it may in turn be rescheduled
    again, forming a reschedule loop."

    Design: Difficulty/non_linear_state_machine/visit_reschedule_cycle_scheduled_to_rescheduled_to_scheduled
    """
    ctx, v1, v2, v3 = _reschedule_chain()
    assert validate_success(api.get_visit(v1["id"], ctx.nurse_headers), 200)["status"] == "RESCHEDULED"
    assert validate_success(api.get_visit(v2["id"], ctx.nurse_headers), 200)["status"] == "RESCHEDULED"
    assert validate_success(api.get_visit(v3["id"], ctx.nurse_headers), 200)["status"] == "SCHEDULED"


def test_reschedule_replacement_points_back_at_superseded_visit(api):
    """PRD 3.5: "the replacement copies the enrollment_id, nurse_id, and phase of the
    original and adopts the new dates, and its rescheduled_from_visit_id is set to the
    superseded visit's id."

    Design: Difficulty/non_linear_state_machine/visit_reschedule_cycle_scheduled_to_rescheduled_to_scheduled
    """
    ctx, v1, v2, v3 = _reschedule_chain()
    assert v2["rescheduled_from_visit_id"] == v1["id"]
    assert v3["rescheduled_from_visit_id"] == v2["id"]


# ─── Difficulty: nurse double-booking (travel buffer) ───
def test_new_visit_within_travel_buffer_conflicts(api):
    """PRD 3.5: "the two windows are said to conflict when the candidate's
    scheduled_start falls before the existing visit's scheduled_end plus the 30-minute
    buffer, and simultaneously the existing visit's scheduled_start falls before the
    candidate's scheduled_end plus the 30-minute buffer." PRD 3.5: "A conflict is
    rejected with ERR_VISIT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/nurse_double_booking_within_travel_buffer
    """
    ctx = setup_shared_nurse_enrollments(count=2)
    e1, e2 = ctx.enrollment_ids
    validate_success(api.create_visit(
        create_visit_payload(e1, ctx.nurse_id, "PREGNANCY", "2026-06-01",
                             "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"),
        ctx.nurse_headers), 201)
    # New visit starts 15 minutes after the existing one ends -> inside the 30-min buffer.
    res = api.create_visit(
        create_visit_payload(e2, ctx.nurse_id, "PREGNANCY", "2026-06-01",
                             "2026-06-01T11:15:00Z", "2026-06-01T12:00:00Z"),
        ctx.nurse_headers)
    validate_error(res, ApiErrorId.ERR_VISIT_OVERLAP.value)


def test_back_to_back_visit_with_full_buffer_gap_does_not_conflict(api):
    """PRD 3.5: "Because the geometry is half-open on the end side, two back-to-back
    visits separated by a gap of at least the full 30 minutes do not conflict."

    Design: Difficulty/resource_temporal_overlap/nurse_double_booking_within_travel_buffer
    """
    ctx = setup_shared_nurse_enrollments(count=2)
    e1, e2 = ctx.enrollment_ids
    validate_success(api.create_visit(
        create_visit_payload(e1, ctx.nurse_id, "PREGNANCY", "2026-06-01",
                             "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z"),
        ctx.nurse_headers), 201)
    # New visit starts exactly 30 minutes after the existing one ends -> no conflict.
    res = api.create_visit(
        create_visit_payload(e2, ctx.nurse_id, "PREGNANCY", "2026-06-01",
                             "2026-06-01T11:30:00Z", "2026-06-01T12:30:00Z"),
        ctx.nurse_headers)
    validate_success(res, 201)


# ─── Difficulty: duplicate target_date per enrollment ───
def test_second_visit_same_enrollment_same_target_date_rejected(api):
    """PRD 3.5: "no two non-terminal visits of the same enrollment may share the same
    target_date, and a collision is rejected with ERR_DUPLICATE_TARGET_DATE."

    Design: Difficulty/resource_temporal_overlap/duplicate_target_date_same_enrollment
    """
    ctx = setup_active_enrollment()
    n2 = create_nurse(full_name="N Dup2")
    schedule_visit(
        ctx, target_date="2026-06-05",
        scheduled_start="2026-06-05T09:00:00Z", scheduled_end="2026-06-05T10:00:00Z",
    )
    # Different nurse, non-overlapping time, but same enrollment + same target_date.
    res = api.create_visit(
        create_visit_payload(ctx.enrollment_id, n2["id"], "PREGNANCY", "2026-06-05",
                             "2026-06-05T14:00:00Z", "2026-06-05T15:00:00Z"),
        make_nurse_headers(n2["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_TARGET_DATE.value)


def test_second_visit_same_enrollment_different_target_date_accepted(api):
    """PRD 3.5: "no two non-terminal visits of the same enrollment may share the same
    target_date, and a collision is rejected with ERR_DUPLICATE_TARGET_DATE."

    Design: Difficulty/resource_temporal_overlap/duplicate_target_date_same_enrollment
    """
    ctx = setup_active_enrollment()
    schedule_visit(
        ctx, target_date="2026-06-05",
        scheduled_start="2026-06-05T09:00:00Z", scheduled_end="2026-06-05T10:00:00Z",
    )
    # A distinct target_date on the same enrollment must be accepted.
    res = api.create_visit(
        create_visit_payload(ctx.enrollment_id, ctx.nurse_id, "PREGNANCY", "2026-06-06",
                             "2026-06-06T09:00:00Z", "2026-06-06T10:00:00Z"),
        ctx.nurse_headers)
    validate_success(res, 201)


# ─── Difficulty: completion requires ACTIVE enrollment ──
def test_complete_visit_on_enrolled_but_inactive_enrollment_rejected(api):
    """PRD 3.6: "The visit must be `SCHEDULED` and its enrollment must be `ACTIVE`; an enrollment that is not `ACTIVE` yields `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_enrollment_active
    """
    ctx = setup_enrolled_enrollment()  # ENROLLED, never assigned so not ACTIVE
    visit = schedule_visit(
        ctx, target_date="2026-02-15",
        scheduled_start="2026-02-15T09:00:00Z", scheduled_end="2026-02-15T10:00:00Z",
    )
    res = api.complete_visit(
        visit["id"], complete_visit_payload("2026-02-15"), ctx.nurse_headers
    )
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_rejected_completion_leaves_visit_scheduled(api):
    """PRD 3.6: "The visit must be `SCHEDULED` and its enrollment must be `ACTIVE`; an enrollment that is not `ACTIVE` yields `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/visit_complete_requires_enrollment_active
    """
    ctx = setup_enrolled_enrollment()
    visit = schedule_visit(
        ctx, target_date="2026-02-15",
        scheduled_start="2026-02-15T09:00:00Z", scheduled_end="2026-02-15T10:00:00Z",
    )
    api.complete_visit(visit["id"], complete_visit_payload("2026-02-15"), ctx.nurse_headers)
    after = validate_success(api.get_visit(visit["id"], ctx.nurse_headers), 200)
    assert after["status"] == "SCHEDULED"
    assert after["completed_date"] is None


# ─── Corner: schedule window coherence ──────────────────
def test_schedule_window_end_not_after_start_rejected(api):
    """PRD 3.5: "The scheduling window must be coherent: scheduled_end must be strictly
    after scheduled_start, and a window where it is not is rejected with
    ERR_SCHEDULE_WINDOW_INVALID."

    Design: Corner/validations/visit_schedule_window_invalid_rejected
    """
    ctx = setup_active_enrollment()
    res = api.create_visit(
        create_visit_payload(ctx.enrollment_id, ctx.nurse_id, "PREGNANCY", "2026-06-01",
                             "2026-06-01T11:00:00Z", "2026-06-01T10:00:00Z"),
        ctx.nurse_headers)
    validate_error(res, ApiErrorId.ERR_SCHEDULE_WINDOW_INVALID.value)


# ─── Corner: enrollment-filtered visit listing ──────────
def test_visits_filtered_by_enrollment_returns_only_that_enrollment(api):
    """PRD 2.3: "List results are always returned sorted by created_at in ascending
    order (oldest first), and any additional filters an endpoint offers are applied
    before pagination."

    Design: Corner/endpoints/visits_filtered_by_enrollment_reverse_reachability
    """
    ctx = setup_active_enrollment()
    v1 = schedule_visit(
        ctx, target_date="2026-06-15",
        scheduled_start="2026-06-15T09:00:00Z", scheduled_end="2026-06-15T10:00:00Z",
    )
    data, meta = validate_paginated(
        api.list_visits(ctx.supervisor_headers, params={"enrollment_id": ctx.enrollment_id})
    )
    assert len(data) == 1
    assert data[0]["id"] == v1["id"]
    assert data[0]["status"] == "SCHEDULED"
