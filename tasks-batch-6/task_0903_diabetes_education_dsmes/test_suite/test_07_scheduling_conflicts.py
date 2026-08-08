"""Temporal and capacity conflicts, and validation-precedence pairs.

Queue A (Difficulty): resource_temporal_overlap (dietitian half-open, room
buffer), priority_pair_validation_conflict (state>fiscal, temporal>constraint).
Queue B (Corner): validations (invalid time range, group full).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment, add_active_enrollment,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]


# --- rt_dietitian_double_book_half_open ---
def test_dietitian_overlapping_session_rejected(api):
    """PRD §3.4: "if the dietitian already has another non-terminal individual
    session whose time window overlaps the requested `[scheduled_start,
    scheduled_end)` window, the request is rejected with
    `ERR_DIETITIAN_DOUBLE_BOOKED`."

    A second session 09:30-10:30 overlaps an existing 09:00-10:00 booking for the
    same dietitian.

    Design: Difficulty/resource_temporal_overlap/rt_dietitian_double_book_half_open
    """
    ctx = setup_active_enrollment(api)
    th.schedule_individual_session_ok(api, ctx, "2026-05-12T09:00:00Z", "2026-05-12T10:00:00Z")
    resp = th.schedule_individual_session(api, ctx, "2026-05-12T09:30:00Z", "2026-05-12T10:30:00Z")
    validate_error(resp, ApiErrorId.ERR_DIETITIAN_DOUBLE_BOOKED.value)


def test_dietitian_touching_sessions_allowed(api):
    """PRD §3.4: "Overlap is evaluated on a half-open basis, so two sessions that
    merely touch at an endpoint (one ends exactly when the next begins) do not
    conflict."

    A session 10:00-11:00 that begins exactly when the 09:00-10:00 session ends
    is accepted.

    Design: Difficulty/resource_temporal_overlap/rt_dietitian_double_book_half_open
    """
    ctx = setup_active_enrollment(api)
    th.schedule_individual_session_ok(api, ctx, "2026-05-12T09:00:00Z", "2026-05-12T10:00:00Z")
    second = th.schedule_individual_session_ok(api, ctx, "2026-05-12T10:00:00Z", "2026-05-12T11:00:00Z")
    assert second["encounter_status"] == "SCHEDULED", \
        f"touching session must schedule, got {second['encounter_status']}"


# --- rt_group_room_buffer_conflict ---
def test_room_buffer_conflict_within_15_minutes(api):
    """PRD §3.5: "a new class in the same `room_id` must keep at least a 15-minute
    gap from every other class already booked in that room, where the comparison
    treats each class's time span as a closed interval and additionally requires
    the 15-minute cushion between them; a class that falls within that buffered
    window of another is rejected with `ERR_ROOM_CONFLICT`."

    A second ROOM-1 class starting 14:10 — only 10 minutes after a 13:00-14:00
    class ends — is rejected.

    Design: Difficulty/resource_temporal_overlap/rt_group_room_buffer_conflict
    """
    ctx = setup_active_enrollment(api)
    th.make_group_class_ok(api, ctx, room_id="ROOM-1",
                           scheduled_start="2026-05-14T13:00:00Z", scheduled_end="2026-05-14T14:00:00Z",
                           capacity=10, topic="Carb Counting")
    resp = th.make_group_class(api, ctx, room_id="ROOM-1",
                               scheduled_start="2026-05-14T14:10:00Z", scheduled_end="2026-05-14T15:00:00Z",
                               capacity=10, topic="Foot Care")
    validate_error(resp, ApiErrorId.ERR_ROOM_CONFLICT.value)


def test_room_conflict_scoped_to_same_room(api):
    """PRD §3.5: "a new class in the same `room_id` must keep at least a 15-minute
    gap from every other class already booked in that room".

    The buffer is scoped to the same room: a class in a different room (ROOM-2) at
    the very same time as a ROOM-1 class raises no room conflict and is accepted.

    Design: Difficulty/resource_temporal_overlap/rt_group_room_buffer_conflict
    """
    ctx = setup_active_enrollment(api)
    th.make_group_class_ok(api, ctx, room_id="ROOM-1",
                           scheduled_start="2026-05-14T13:00:00Z", scheduled_end="2026-05-14T14:00:00Z",
                           capacity=10, topic="Carb Counting")
    second = th.make_group_class_ok(api, ctx, room_id="ROOM-2",
                                    scheduled_start="2026-05-14T13:00:00Z", scheduled_end="2026-05-14T14:00:00Z",
                                    capacity=10, topic="Foot Care")
    assert second["seats_taken"] == 0, f"new class must start with 0 seats, got {second['seats_taken']}"


# --- pc_state_beats_fiscal_on_schedule ---
def test_suspended_enrollment_state_gate_beats_benefit_cap(api):
    """PRD §2.7: "checks are evaluated in a fixed priority order, and the first
    failure encountered determines the response."
    PRD §2.7: "**Enrollment-active gate** — the governing enrollment is `ACTIVE`
    where scheduling or device activation requires it, else
    `ERR_ENROLLMENT_NOT_ACTIVE` (409)."

    Scheduling an 11-hour session (which also exceeds the 10.0h cap) on a
    SUSPENDED enrollment returns the higher-priority ERR_ENROLLMENT_NOT_ACTIVE.

    Design: Difficulty/priority_pair_validation_conflict/pc_state_beats_fiscal_on_schedule
    """
    ctx = setup_active_enrollment(api)
    th.suspend_via_no_shows(api, ctx, total_sessions=3, strikes=3, base_day="2026-05-15")
    resp = th.schedule_individual_session(api, ctx, "2026-05-16T08:00:00Z", "2026-05-16T19:00:00Z")
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_active_enrollment_over_cap_hits_benefit_error(api):
    """PRD §2.7: "**Benefit budget** — the schedule fits within the benefit cap,
    else `ERR_BENEFIT_HOURS_EXCEEDED` (402)."

    Control: on an ACTIVE enrollment (state gate passes) the same over-cap
    11-hour session yields the lower-priority ERR_BENEFIT_HOURS_EXCEEDED,
    confirming the state gate is what pre-empts it when suspended.

    Design: Difficulty/priority_pair_validation_conflict/pc_state_beats_fiscal_on_schedule
    """
    ctx = setup_active_enrollment(api)
    resp = th.schedule_individual_session(api, ctx, "2026-05-16T08:00:00Z", "2026-05-16T19:00:00Z")
    validate_error(resp, ApiErrorId.ERR_BENEFIT_HOURS_EXCEEDED.value)


# --- pc_temporal_beats_constraint_on_group_seat ---
def test_patient_time_conflict_beats_group_full(api):
    """PRD §2.7: "checks are evaluated in a fixed priority order, and the first
    failure encountered determines the response."
    PRD §2.7: "**Patient availability** — no patient time conflict for a group
    reservation, else `ERR_PATIENT_TIME_CONFLICT` (409)."

    Reserving a seat on a full capacity-1 class for a patient who already has an
    overlapping individual session returns the higher-priority
    ERR_PATIENT_TIME_CONFLICT rather than ERR_GROUP_CLASS_FULL.

    Design: Difficulty/priority_pair_validation_conflict/pc_temporal_beats_constraint_on_group_seat
    """
    ctx = setup_active_enrollment(api)  # patient P (ctx["enrollment_id"])
    # Second patient Q shares the same program/curriculum/dietitian as P.
    q = add_active_enrollment(api, ctx)
    gc = th.make_group_class_ok(api, ctx, room_id="ROOM-1",
                                scheduled_start="2026-05-20T13:00:00Z", scheduled_end="2026-05-20T14:00:00Z",
                                capacity=1, topic="Nutrition Basics")
    th.reserve_seat_ok(api, ctx, gc["id"], q["id"])  # Q fills the only seat
    # P gets an individual session overlapping the class window.
    th.schedule_individual_session_ok(api, ctx, "2026-05-20T13:30:00Z", "2026-05-20T13:45:00Z")
    resp = th.reserve_seat(api, ctx, gc["id"], ctx["enrollment_id"])
    validate_error(resp, ApiErrorId.ERR_PATIENT_TIME_CONFLICT.value)


def test_group_full_fires_when_no_patient_conflict(api):
    """PRD §2.7: "**Seat capacity** — the class has a free seat, else
    `ERR_GROUP_CLASS_FULL` (409)."

    Control: a patient with no overlapping session reserving on the same full
    class yields ERR_GROUP_CLASS_FULL, confirming the patient-conflict check is
    what pre-empts it in the sibling test.

    Design: Difficulty/priority_pair_validation_conflict/pc_temporal_beats_constraint_on_group_seat
    """
    ctx = setup_active_enrollment(api)
    q = add_active_enrollment(api, ctx)
    gc = th.make_group_class_ok(api, ctx, room_id="ROOM-1",
                                scheduled_start="2026-05-20T13:00:00Z", scheduled_end="2026-05-20T14:00:00Z",
                                capacity=1, topic="Nutrition Basics")
    th.reserve_seat_ok(api, ctx, gc["id"], q["id"])  # Q fills the only seat
    # P (ctx enrollment) has no overlapping session.
    resp = th.reserve_seat(api, ctx, gc["id"], ctx["enrollment_id"])
    validate_error(resp, ApiErrorId.ERR_GROUP_CLASS_FULL.value)


# --- Queue B: val_invalid_time_range_on_session ---
def test_session_zero_length_time_range_rejected(api):
    """PRD §3.4: "The `scheduled_end` must be strictly after `scheduled_start`,
    or the request is rejected with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/val_invalid_time_range_on_session
    """
    ctx = setup_active_enrollment(api)
    resp = th.schedule_individual_session(api, ctx, "2026-05-25T09:00:00Z", "2026-05-25T09:00:00Z")
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)


# --- Queue B: val_group_class_full_on_reserve ---
def test_reserve_seat_on_full_class_rejected(api):
    """PRD §3.5: "if `seats_taken` (measured before this reservation) has already
    reached `capacity`, the reservation is rejected with `ERR_GROUP_CLASS_FULL`."

    Design: Corner/validations/val_group_class_full_on_reserve
    """
    ctx = setup_active_enrollment(api)
    q = add_active_enrollment(api, ctx)
    gc = th.make_group_class_ok(api, ctx, room_id="ROOM-7",
                                scheduled_start="2026-05-27T13:00:00Z", scheduled_end="2026-05-27T14:00:00Z",
                                capacity=1, topic="Full Class")
    th.reserve_seat_ok(api, ctx, gc["id"], q["id"])
    resp = th.reserve_seat(api, ctx, gc["id"], ctx["enrollment_id"])
    validate_error(resp, ApiErrorId.ERR_GROUP_CLASS_FULL.value)
