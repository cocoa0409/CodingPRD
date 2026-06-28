"""Scheduling a session: the booking battery, validation precedence, temporal
overlap semantics, weekly-cap and visit-cap boundaries.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_appointment_payload, TEST_USERS, make_evaluator_headers,
    set_clock, create_child, create_therapist, create_finalized_evaluation,
    create_active_plan, create_authorization, setup_active_care,
    book_appointment, book_appointment_ok, get_authorization, get_appointment,
)
from test_helpers import create_plan_of_care_payload

ADMIN = TEST_USERS["clinic_admin_headers"]


# ─── priority_pair_validation_conflict / double_booked_outranks_visit_cap_exceeded ─

def test_double_booked_outranks_visit_cap_exceeded(api):
    """PRD §3.5: "Then therapist double-booking, then child double-booking, then
    the therapist weekly-minutes cap, and finally — as the last business check —
    the visit-cap capacity test." A booking that both overlaps the therapist's
    SCHEDULED slot AND draws on a zero-available authorization reports the
    higher-priority therapist double-booking, not the visit-cap error.

    Design: Difficulty/priority_pair_validation_conflict/double_booked_outranks_visit_cap_exceeded
    """
    # authorized_visits=1 reserved by the first 09:00-09:45 appointment -> available 0.
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=1)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    # Second booking overlaps the same therapist slot AND draws on the zero auth.
    res = book_appointment(ctx, "2026-06-08T09:30:00Z", "2026-06-08T10:15:00Z")
    validate_error(res, "ERR_THERAPIST_DOUBLE_BOOKED")


def test_visit_cap_reported_when_only_capacity_violated(api):
    """PRD §3.5: "a capacity failure is only reported once every scheduling and
    referential constraint has passed, so `ERR_VISIT_CAP_EXCEEDED` is the last
    word, not a mask over an earlier problem." Control for the precedence pair:
    with no overlap, the same zero-available authorization surfaces the fiscal
    error that double-booking was masking.

    Design: Difficulty/priority_pair_validation_conflict/double_booked_outranks_visit_cap_exceeded
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=1)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    # Non-overlapping, later slot the same week (within weekly cap), zero auth.
    res = book_appointment(ctx, "2026-06-08T11:00:00Z", "2026-06-08T11:45:00Z")
    validate_error(res, "ERR_VISIT_CAP_EXCEEDED")


# ─── priority_pair_validation_conflict / discipline_mismatch_outranks_weekly_cap ─

def test_discipline_mismatch_outranks_weekly_cap_exceeded(api):
    """PRD §3.5: "first the referential checks — that the therapist's discipline
    equals the authorization's discipline ... any of which fails with
    `ERR_THERAPIST_DISCIPLINE_MISMATCH`." PRD §3.5: "Then therapist
    double-booking, then child double-booking, then the therapist weekly-minutes
    cap". The referential discipline check (earlier) outranks the weekly-cap check.

    Design: Difficulty/priority_pair_validation_conflict/discipline_mismatch_outranks_weekly_cap_exceeded
    """
    set_clock("2026-06-05T12:00:00Z")
    # OT therapist with a tiny weekly cap so a 45-min booking alone exceeds it.
    th_ot = create_therapist(full_name="OT Cap", discipline="OT", max_caseload=5,
                             weekly_visit_minutes_cap=30)
    th_slp = create_therapist(full_name="SLP Primary", discipline="SLP", max_caseload=5,
                              weekly_visit_minutes_cap=600)
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th_slp["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th_slp["id"])
    auth_slp = create_authorization(child["id"], discipline="SLP", authorized_visits=3)
    # Book a 45-min appt on the OT therapist drawing the SLP authorization.
    res = api.create_appointment(
        create_appointment_payload(child["id"], th_ot["id"], auth_slp["id"], plan["id"],
                                   "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z"),
        ADMIN)
    validate_error(res, "ERR_THERAPIST_DISCIPLINE_MISMATCH")


def test_weekly_cap_reported_when_discipline_matches(api):
    """PRD §3.5: "the therapist's already-scheduled minutes for the appointment's
    ISO week plus the new `duration_minutes` must not exceed
    `weekly_visit_minutes_cap`, with equality allowed and only a strict excess
    rejected as `ERR_THERAPIST_WEEKLY_CAP_EXCEEDED`." Control for the precedence
    pair: when discipline matches (no referential failure), the weekly-cap error
    that the mismatch was masking is the one reported.

    Design: Difficulty/priority_pair_validation_conflict/discipline_mismatch_outranks_weekly_cap_exceeded
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP", weekly_visit_minutes_cap=30)
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=3)
    # 45-min booking on a matching-discipline therapist with a 30-min weekly cap.
    res = api.create_appointment(
        create_appointment_payload(child["id"], th["id"], auth["id"], plan["id"],
                                   "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z"),
        ADMIN)
    validate_error(res, "ERR_THERAPIST_WEEKLY_CAP_EXCEEDED")


# ─── boundary_precision_check / therapist_weekly_cap_exact_equals_allows ─────

def test_weekly_cap_exact_equality_allows_booking(api):
    """PRD §2.7: "A prospective booking of duration D in week W is rejected when
    the therapist's already-scheduled minutes for W plus D would be strictly
    greater than `weekly_visit_minutes_cap`." PRD §2.7: "Landing exactly on the
    cap is allowed — equality succeeds; only exceeding it fails." 45 + 45 == 90 ==
    cap succeeds.

    Design: Difficulty/boundary_precision_check/therapist_weekly_cap_exact_equals_allows
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP",
                            weekly_visit_minutes_cap=90, planned_weekly_minutes=90)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    res = book_appointment(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    appt2 = validate_success(res, 201)
    assert appt2["status"] == "SCHEDULED", appt2
    assert appt2["duration_minutes"] == 45, appt2


def test_weekly_cap_one_minute_over_rejected(api):
    """PRD §2.7: "A prospective booking of duration D in week W is rejected when
    the therapist's already-scheduled minutes for W plus D would be strictly
    greater than `weekly_visit_minutes_cap`." One minute past the cap (45 + 46 =
    91 > 90) crosses the boundary and is rejected.

    Design: Difficulty/boundary_precision_check/therapist_weekly_cap_exact_equals_allows
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP",
                            weekly_visit_minutes_cap=90, planned_weekly_minutes=90)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    # 46-minute second booking: 45 + 46 = 91 > 90.
    res = book_appointment(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:46:00Z")
    validate_error(res, "ERR_THERAPIST_WEEKLY_CAP_EXCEEDED")


# ─── cross_entity_state_dependency / booking_requires_authorization_active_not_expired ─

def test_booking_against_expired_authorization_rejected(api):
    """PRD §3.4: "Expiry is driven by the clock: when the logical clock reaches
    `valid_until`, an `ACTIVE` authorization automatically transitions to
    `EXPIRED`, after which no new reservation may draw on it." PRD §3.5: "the
    authorization must be `ACTIVE` and the requested interval must satisfy
    `valid_from` at or before `start_time` and `end_time` at or before
    `valid_until`, otherwise `ERR_AUTH_WINDOW_VIOLATION`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_authorization_active_not_expired
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP")
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=3,
                                valid_from="2026-06-01T00:00:00Z",
                                valid_until="2026-06-15T00:00:00Z")
    # Advance the clock past valid_until to auto-expire the authorization.
    validate_success(api.set_clock("2026-06-16T00:00:00Z", ADMIN), 200)
    assert get_authorization(auth["id"])["status"] == "EXPIRED"
    res = api.create_appointment(
        create_appointment_payload(child["id"], th["id"], auth["id"], plan["id"],
                                   "2026-06-12T09:00:00Z", "2026-06-12T09:45:00Z"),
        ADMIN)
    validate_error(res, "ERR_AUTH_WINDOW_VIOLATION")


def test_booking_against_active_authorization_in_window_succeeds(api):
    """PRD §3.5: "the authorization must be `ACTIVE` and the requested interval
    must satisfy `valid_from` at or before `start_time` and `end_time` at or
    before `valid_until`, otherwise `ERR_AUTH_WINDOW_VIOLATION`." Positive
    control: while the authorization is ACTIVE and the slot is inside its window,
    booking is accepted.

    Design: Difficulty/cross_entity_state_dependency/booking_requires_authorization_active_not_expired
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP")
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=3,
                                valid_from="2026-06-01T00:00:00Z",
                                valid_until="2026-06-15T00:00:00Z")
    assert get_authorization(auth["id"])["status"] == "ACTIVE"
    res = api.create_appointment(
        create_appointment_payload(child["id"], th["id"], auth["id"], plan["id"],
                                   "2026-06-12T09:00:00Z", "2026-06-12T09:45:00Z"),
        ADMIN)
    appt = validate_success(res, 201)
    assert appt["status"] == "SCHEDULED", appt


# ─── resource_temporal_overlap / therapist_overlap_half_open_adjacency_allowed ─

def test_therapist_adjacent_booking_allowed(api):
    """PRD §3.5: "The therapist double-booking check forbids the requested
    half-open interval `[start_time, end_time)` from overlapping any existing
    `SCHEDULED` appointment for the same therapist; exact adjacency, where one
    appointment's `end_time` equals the next one's `start_time`, is allowed and
    does not conflict".

    Design: Difficulty/resource_temporal_overlap/therapist_overlap_half_open_adjacency_allowed
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP", max_caseload=9, weekly_visit_minutes_cap=600)
    # Child A: first 09:00-09:45 appointment.
    child_a = create_child(full_name="Child A")
    ev_a = create_finalized_evaluation(child_a["id"], th["id"], discipline="SLP")
    plan_a = create_active_plan(child_a["id"], ev_a["id"], th["id"])
    auth_a = create_authorization(child_a["id"], discipline="SLP", authorized_visits=3)
    validate_success(api.create_appointment(
        create_appointment_payload(child_a["id"], th["id"], auth_a["id"], plan_a["id"],
                                   "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z"), ADMIN), 201)
    # Child B: back-to-back 09:45-10:30 on the same therapist (adjacent, allowed).
    child_b = create_child(full_name="Child B")
    ev_b = create_finalized_evaluation(child_b["id"], th["id"], discipline="SLP")
    plan_b = create_active_plan(child_b["id"], ev_b["id"], th["id"])
    auth_b = create_authorization(child_b["id"], discipline="SLP", authorized_visits=3)
    res = api.create_appointment(
        create_appointment_payload(child_b["id"], th["id"], auth_b["id"], plan_b["id"],
                                   "2026-06-08T09:45:00Z", "2026-06-08T10:30:00Z"), ADMIN)
    appt_b = validate_success(res, 201)
    assert appt_b["status"] == "SCHEDULED", appt_b


def test_therapist_true_overlap_rejected(api):
    """PRD §3.5: "The therapist double-booking check forbids the requested
    half-open interval `[start_time, end_time)` from overlapping any existing
    `SCHEDULED` appointment for the same therapist ... a violation is
    `ERR_THERAPIST_DOUBLE_BOOKED`." A 09:30 start inside an existing 09:00-09:45
    slot truly overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/therapist_overlap_half_open_adjacency_allowed
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP", max_caseload=9, weekly_visit_minutes_cap=600)
    child_a = create_child(full_name="Child A")
    ev_a = create_finalized_evaluation(child_a["id"], th["id"], discipline="SLP")
    plan_a = create_active_plan(child_a["id"], ev_a["id"], th["id"])
    auth_a = create_authorization(child_a["id"], discipline="SLP", authorized_visits=3)
    validate_success(api.create_appointment(
        create_appointment_payload(child_a["id"], th["id"], auth_a["id"], plan_a["id"],
                                   "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z"), ADMIN), 201)
    child_b = create_child(full_name="Child B")
    ev_b = create_finalized_evaluation(child_b["id"], th["id"], discipline="SLP")
    plan_b = create_active_plan(child_b["id"], ev_b["id"], th["id"])
    auth_b = create_authorization(child_b["id"], discipline="SLP", authorized_visits=3)
    res = api.create_appointment(
        create_appointment_payload(child_b["id"], th["id"], auth_b["id"], plan_b["id"],
                                   "2026-06-08T09:30:00Z", "2026-06-08T10:15:00Z"), ADMIN)
    validate_error(res, "ERR_THERAPIST_DOUBLE_BOOKED")


# ─── resource_temporal_overlap / child_overlap_buffered_adjacency_rejected ───

def _setup_child_with_two_therapists(api):
    """Helper: one child with two SLP therapists each ACTIVE-planned, plus one
    authorization. Returns (child, th1, th2, plan1, auth)."""
    set_clock("2026-06-05T12:00:00Z")
    th1 = create_therapist(full_name="T One", discipline="SLP", max_caseload=9,
                           weekly_visit_minutes_cap=600)
    th2 = create_therapist(full_name="T Two", discipline="SLP", max_caseload=9,
                           weekly_visit_minutes_cap=600)
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th1["id"], discipline="SLP")
    plan1 = create_active_plan(child["id"], ev["id"], th1["id"])
    auth = create_authorization(child["id"], discipline="SLP", authorized_visits=3)
    return child, th1, th2, plan1, auth


def test_child_buffered_adjacency_rejected(api):
    """PRD §3.5: "each existing interval is expanded by 15 minutes on its end, so
    even true adjacency (the new start equal to an existing end) conflicts for the
    same child. That violation is `ERR_CHILD_DOUBLE_BOOKED`." A second appointment
    for the same child starting exactly at the first's end (09:45) is rejected.

    Design: Difficulty/resource_temporal_overlap/child_overlap_buffered_adjacency_rejected
    """
    child, th1, th2, plan1, auth = _setup_child_with_two_therapists(api)
    validate_success(api.create_appointment(
        create_appointment_payload(child["id"], th1["id"], auth["id"], plan1["id"],
                                   "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z"), ADMIN), 201)
    # Same child, free therapist-2, adjacent start at 09:45 -> within buffer.
    res = api.create_appointment(
        create_appointment_payload(child["id"], th2["id"], auth["id"], plan1["id"],
                                   "2026-06-08T09:45:00Z", "2026-06-08T10:30:00Z"), ADMIN)
    validate_error(res, "ERR_CHILD_DOUBLE_BOOKED")


def test_child_booking_beyond_buffer_allowed(api):
    """PRD §3.5: "The new interval conflicts with an existing `SCHEDULED`
    appointment for the same child whenever the new `start_time` is earlier than
    that existing appointment's `end_time` plus 15 minutes and the existing
    appointment's start is earlier than the new `end_time` plus 15 minutes". A
    second session starting at 10:00 (15 minutes past the 09:45 end) clears the
    buffer and is allowed.

    Design: Difficulty/resource_temporal_overlap/child_overlap_buffered_adjacency_rejected
    """
    child, th1, th2, plan1, auth = _setup_child_with_two_therapists(api)
    validate_success(api.create_appointment(
        create_appointment_payload(child["id"], th1["id"], auth["id"], plan1["id"],
                                   "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z"), ADMIN), 201)
    # Same child, therapist-2, start 10:00 == 09:45 + 15 min -> not earlier than
    # end+15, so no conflict.
    res = api.create_appointment(
        create_appointment_payload(child["id"], th2["id"], auth["id"], plan1["id"],
                                   "2026-06-08T10:00:00Z", "2026-06-08T10:45:00Z"), ADMIN)
    appt = validate_success(res, 201)
    assert appt["status"] == "SCHEDULED", appt


# ─── Corner: appointment_initial_state_is_scheduled ──────────────────────────

def test_new_appointment_is_scheduled_with_computed_duration(api):
    """PRD §3.5: "A successful booking creates the appointment in `SCHEDULED`
    status with `duration_minutes` computed as the whole minutes between
    `start_time` and `end_time`".

    Design: Corner/state_machines/appointment_initial_state_is_scheduled
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z")
    res = book_appointment(ctx, "2026-06-10T09:00:00Z", "2026-06-10T10:00:00Z")
    appt = validate_success(res, 201)
    assert appt["status"] == "SCHEDULED"
    assert appt["duration_minutes"] == 60, appt


# ─── Corner: visit_cap_exceeded_at_zero_available ────────────────────────────

def test_visit_cap_exceeded_at_zero_available(api):
    """PRD §3.4: "while `EXHAUSTED` any new reservation against it is rejected with
    `ERR_VISIT_CAP_EXCEEDED`." PRD §2.6: "A new reservation is permitted only when
    `available_visits` is at least 1 before the reservation is taken."

    Design: Corner/calculations/visit_cap_exceeded_at_zero_available
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=1)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    # Non-overlapping second slot, within weekly cap, but auth is now zero-available.
    res = book_appointment(ctx, "2026-06-08T11:00:00Z", "2026-06-08T11:45:00Z")
    validate_error(res, "ERR_VISIT_CAP_EXCEEDED")


# ─── Corner: weekly_cap_exceeded_above_cap_rejected ──────────────────────────

def test_weekly_cap_exceeded_above_cap_rejected(api):
    """PRD §2.7: "A prospective booking of duration D in week W is rejected when
    the therapist's already-scheduled minutes for W plus D would be strictly
    greater than `weekly_visit_minutes_cap`." With cap 60 and an existing 45-min
    appointment, a second 45-min booking (45 + 45 = 90 > 60) is rejected.

    Design: Corner/calculations/weekly_cap_exceeded_above_cap_rejected
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP",
                            weekly_visit_minutes_cap=60)
    book_appointment_ok(ctx, "2026-06-08T09:00:00Z", "2026-06-08T09:45:00Z")
    res = book_appointment(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    validate_error(res, "ERR_THERAPIST_WEEKLY_CAP_EXCEEDED")


# ─── Corner: existence_before_state_booking_unknown_authorization ────────────

def test_booking_unknown_authorization_is_not_found(api):
    """PRD §2.5: "The same `ERR_NOT_FOUND` applies when a foreign-key identifier
    supplied in a request body ... does not resolve to an existing resource.
    Existence is checked before any state or business rule is evaluated."

    Design: Corner/validations/existence_before_state_booking_unknown_authorization
    """
    set_clock("2026-06-05T12:00:00Z")
    th = create_therapist(discipline="SLP")
    child = create_child()
    ev = create_finalized_evaluation(child["id"], th["id"], discipline="SLP")
    plan = create_active_plan(child["id"], ev["id"], th["id"])
    res = api.create_appointment(
        create_appointment_payload(child["id"], th["id"],
                                   "00000000-0000-4000-8000-0000000000ff", plan["id"],
                                   "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z"),
        ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Corner: child_appointments_filtered_list_reverse_reachability ───────────

def test_appointments_filtered_by_child(api):
    """PRD §3.1: "`active_appointment_count` ... the running count of that child's
    appointments currently in `SCHEDULED` status." PRD §2.2: "The `response_type`
    is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/child_appointments_filtered_list_reverse_reachability
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z")
    book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    res = api.list_appointments(ADMIN, params={"child_id": ctx["child"]["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1, meta


# ─── Corner: booking_side_effects_visible_same_response ──────────────────────

def test_booking_side_effects_immediately_visible(api):
    """PRD §3.5: "A successful booking ... increases the chosen authorization's
    `reserved_visits` by 1, recomputes `available_visits`". PRD §2.6:
    "`available_visits` is `authorized_visits` minus `reserved_visits` minus
    `committed_visits`."

    Design: Corner/consistency_model/booking_side_effects_visible_same_response
    """
    ctx = setup_active_care(clock="2026-06-05T12:00:00Z", discipline="SLP", authorized_visits=3)
    book_appointment_ok(ctx, "2026-06-10T09:00:00Z", "2026-06-10T09:45:00Z")
    auth = get_authorization(ctx["auth"]["id"])
    assert auth["reserved_visits"] == 1, auth
    assert auth["available_visits"] == 2, auth
