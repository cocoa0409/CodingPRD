"""Temporal boundaries and resource-overlap rules.

Covers the inclusive lesson-cancellation cutoff (PRD §3.7), pairwise
service-visit window overlap (PRD §3.7), and the half-open pasture concurrent
capacity rule with its inclusive boundary (PRD §3.10).
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_owner, create_owner_with_signed_waiver,
    create_stall, create_pasture, create_horse,
    create_active_boarding, create_lesson, create_turnout,
    create_service_visit, schedule_service_visit, set_clock,
    make_owner_headers, TEST_USERS,
)

BM = TEST_USERS["barn_manager_headers"]


# ===========================================================================
# Difficulty: boundary_precision_check
# ===========================================================================
def test_pasture_third_overlapping_turnout_over_capacity_rejected(api):
    """PRD §3.10: "The booking is rejected with `ERR_PASTURE_FULL` if, at any instant
    in the proposed window, that concurrent count would exceed the pasture's
    `capacity`. Reaching exactly capacity is allowed; only exceeding it is rejected."

    Design: Difficulty/boundary_precision_check/pasture_capacity_at_exactly_capacity_allowed
    """
    ctx = create_active_boarding()
    pasture = create_pasture(capacity=2, label="P-2", daily_rate_cents=1000)
    create_turnout(ctx["horse"]["id"], pasture["id"],
                   "2026-07-01T08:00:00.000Z", "2026-07-01T12:00:00.000Z")
    create_turnout(ctx["horse"]["id"], pasture["id"],
                   "2026-07-01T09:00:00.000Z", "2026-07-01T11:00:00.000Z")
    # Third turnout overlapping both -> concurrent 3 > capacity 2.
    res = api.create_turnout(
        {
            "horse_id": ctx["horse"]["id"],
            "pasture_id": pasture["id"],
            "window_start": "2026-07-01T10:00:00.000Z",
            "window_end": "2026-07-01T10:30:00.000Z",
        },
        BM,
    )
    validate_error(res, "ERR_PASTURE_FULL", expected_status=409)


def test_pasture_second_overlapping_turnout_at_exactly_capacity_allowed(api):
    """PRD §3.10: "Reaching exactly capacity is allowed; only exceeding it is
    rejected."

    Design: Difficulty/boundary_precision_check/pasture_capacity_at_exactly_capacity_allowed
    """
    ctx = create_active_boarding()
    pasture = create_pasture(capacity=2, label="P-2b", daily_rate_cents=1000)
    create_turnout(ctx["horse"]["id"], pasture["id"],
                   "2026-07-01T08:00:00.000Z", "2026-07-01T12:00:00.000Z")
    # Second overlapping turnout -> concurrent 2 == capacity 2, allowed.
    res = api.create_turnout(
        {
            "horse_id": ctx["horse"]["id"],
            "pasture_id": pasture["id"],
            "window_start": "2026-07-01T09:00:00.000Z",
            "window_end": "2026-07-01T11:00:00.000Z",
        },
        BM,
    )
    booked = validate_success(res, 201)
    assert booked["status"] == "BOOKED"


def test_lesson_cancel_at_exactly_cutoff_allowed(api):
    """PRD §3.7: "the current logical time must be at or before `starts_at` minus 24
    hours; a cancellation requested later than that is rejected with
    `ERR_CANCEL_TOO_LATE` (the boundary is inclusive, so cancelling at exactly 24
    hours before start is allowed). A cancelled lesson has `billed_fee_cents` of zero."

    Design: Difficulty/boundary_precision_check/lesson_cancel_at_exactly_cutoff_allowed
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    horse = create_horse(owner["id"])
    lesson = create_lesson(horse["id"], starts_at="2026-06-10T10:00:00.000Z",
                           ends_at="2026-06-10T11:00:00.000Z", lesson_fee_cents=8000)
    set_clock("2026-06-09T10:00:00.000Z")  # exactly starts_at - 24h
    res = api.transition_lesson(lesson["id"], {"target_status": "CANCELLED"},
                                make_owner_headers(owner["id"]))
    cancelled = validate_success(res, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["billed_fee_cents"] == 0


def test_lesson_cancel_after_cutoff_rejected(api):
    """PRD §3.7: "a cancellation requested later than that is rejected with
    `ERR_CANCEL_TOO_LATE`".

    Design: Difficulty/boundary_precision_check/lesson_cancel_at_exactly_cutoff_allowed
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    horse = create_horse(owner["id"])
    lesson = create_lesson(horse["id"], starts_at="2026-06-10T10:00:00.000Z",
                           ends_at="2026-06-10T11:00:00.000Z", lesson_fee_cents=8000)
    set_clock("2026-06-09T10:00:00.001Z")  # one ms past the cutoff
    res = api.transition_lesson(lesson["id"], {"target_status": "CANCELLED"},
                                make_owner_headers(owner["id"]))
    validate_error(res, "ERR_CANCEL_TOO_LATE", expected_status=409)


# ===========================================================================
# Difficulty: resource_temporal_overlap
# ===========================================================================
def test_service_visit_overlapping_horse_window_rejected(api):
    """PRD §3.7: "scheduling is rejected with `ERR_VISIT_OVERLAP` if any other
    `SCHEDULED` or `COMPLETED` service visit for the *same horse* has a window that
    overlaps this one (a pairwise overlap of the two half-open windows)."

    Design: Difficulty/resource_temporal_overlap/service_visit_pairwise_horse_window_overlap
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    horse = create_horse(owner["id"])
    sv1 = create_service_visit(horse["id"], scheduled_at="2026-06-05T09:00:00.000Z",
                               duration_minutes=60, fee_cents=12000)
    schedule_service_visit(sv1["id"])
    sv2 = create_service_visit(horse["id"], visit_type="VET",
                               scheduled_at="2026-06-05T09:30:00.000Z",
                               duration_minutes=60, fee_cents=20000)
    res = api.transition_service_visit(sv2["id"], {"target_status": "SCHEDULED"}, BM)
    validate_error(res, "ERR_VISIT_OVERLAP", expected_status=409)
    visits, _ = validate_paginated(api.list_horse_service_visits(horse["id"], BM))
    target = [v for v in visits if v["id"] == sv2["id"]][0]
    assert target["status"] == "REQUESTED"


def test_service_visit_non_overlapping_window_scheduled(api):
    """PRD §3.7: "A `BarnManager` schedules a requested visit by requesting target
    status `SCHEDULED`: the visit must be `REQUESTED` (else `ERR_INVALID_STATE`), and
    scheduling is rejected with `ERR_VISIT_OVERLAP` if any other `SCHEDULED` or
    `COMPLETED` service visit for the *same horse* has a window that overlaps this one
    (a pairwise overlap of the two half-open windows)."

    Design: Difficulty/resource_temporal_overlap/service_visit_pairwise_horse_window_overlap
    """
    set_clock("2026-06-01T00:00:00.000Z")
    owner = create_owner()
    horse = create_horse(owner["id"])
    sv1 = create_service_visit(horse["id"], scheduled_at="2026-06-05T09:00:00.000Z",
                               duration_minutes=60, fee_cents=12000)
    schedule_service_visit(sv1["id"])
    # Second window starts exactly when first ends -> half-open, no overlap.
    sv2 = create_service_visit(horse["id"], visit_type="VET",
                               scheduled_at="2026-06-05T10:00:00.000Z",
                               duration_minutes=60, fee_cents=20000)
    res = api.transition_service_visit(sv2["id"], {"target_status": "SCHEDULED"}, BM)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_turnout_aggregate_capacity_overlap_rejected(api):
    """PRD §3.10: "at each instant, count the booked turnouts on that pasture whose
    own half-open window contains the instant, including the proposed one. The booking
    is rejected with `ERR_PASTURE_FULL` if, at any instant in the proposed window, that
    concurrent count would exceed the pasture's `capacity`."

    Design: Difficulty/resource_temporal_overlap/turnout_aggregate_capacity_overlap
    """
    ctx = create_active_boarding()
    pasture = create_pasture(capacity=1, label="P-3", daily_rate_cents=1000)
    create_turnout(ctx["horse"]["id"], pasture["id"],
                   "2026-07-01T08:00:00.000Z", "2026-07-01T12:00:00.000Z")
    res = api.create_turnout(
        {
            "horse_id": ctx["horse"]["id"],
            "pasture_id": pasture["id"],
            "window_start": "2026-07-01T10:00:00.000Z",
            "window_end": "2026-07-01T11:00:00.000Z",
        },
        BM,
    )
    validate_error(res, "ERR_PASTURE_FULL", expected_status=409)


def test_turnout_touching_window_does_not_overlap(api):
    """PRD §3.10: "Because the windows are half-open, two turnouts that merely touch —
    one ending exactly when the next begins — do not overlap and do not count against
    each other at that shared instant."

    Design: Difficulty/resource_temporal_overlap/turnout_aggregate_capacity_overlap
    """
    ctx = create_active_boarding()
    pasture = create_pasture(capacity=1, label="P-3b", daily_rate_cents=1000)
    create_turnout(ctx["horse"]["id"], pasture["id"],
                   "2026-07-01T08:00:00.000Z", "2026-07-01T10:00:00.000Z")
    # Second window begins exactly when first ends -> no overlap on a cap-1 pasture.
    res = api.create_turnout(
        {
            "horse_id": ctx["horse"]["id"],
            "pasture_id": pasture["id"],
            "window_start": "2026-07-01T10:00:00.000Z",
            "window_end": "2026-07-01T12:00:00.000Z",
        },
        BM,
    )
    booked = validate_success(res, 201)
    assert booked["status"] == "BOOKED"
