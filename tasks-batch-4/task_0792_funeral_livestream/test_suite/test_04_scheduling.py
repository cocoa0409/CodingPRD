"""Scheduling readiness, cancellation cascades, credit conservation, and the
venue/operator time-conflict rules.

Queue-A instances under transitive_cascade, cross_entity_state_dependency,
resource_temporal_overlap, and compensating_invariant (credit side); plus the
queue-B confirm-idempotency and insufficient-credits corners.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    setup_home_and_venue, setup_draft_order, setup_booking_confirmed_order,
    setup_scheduled_order,
    create_order, create_booking, create_operator, set_operator_duty, create_assignment,
    transition_order, get_order, get_home, get_booking, get_assignment,
    create_venue_booking_payload, create_camera_assignment_payload,
)

ADMIN = TEST_USERS["admin_headers"]


def _scheduled_order_with_assignment():
    """SCHEDULED order with a CONFIRMED booking and one ASSIGNED camera
    (operator ON_DUTY). Returns base dict with 'operator' and 'assignment'."""
    base = setup_scheduled_order(
        initial_credits=1, camera_count=1,
        scheduled_start="2026-06-07T10:00:00Z", scheduled_end="2026-06-07T12:00:00Z",
    )
    op = create_operator(base["home"]["id"], skill="CAMERA")
    set_operator_duty(op["id"], "ON_DUTY")
    base["operator"] = op
    base["assignment"] = create_assignment(base["order"]["id"], op["id"], "CAMERA")
    return base


# --- transitive_cascade: CANCEL -> booking RELEASED -> camera RELEASED --------
def test_cancel_scheduled_order_releases_booking_and_camera(api):
    """PRD §2.8: "When a service order is cancelled, every venue booking of that
    order still in `HELD` or `CONFIRMED` is moved to `RELEASED`, and each such
    release in turn moves every `ASSIGNED` camera assignment of that order's crew
    to `RELEASED`."

    Design: Difficulty/transitive_cascade/cancel_scheduled_order_cascades_booking_then_camera_release
    """
    base = _scheduled_order_with_assignment()
    transition_order(base["order"]["id"], "CANCEL")
    assert get_booking(base["booking"]["id"])["status"] == "RELEASED"
    assert get_assignment(base["assignment"]["id"])["status"] == "RELEASED"


def test_cancel_scheduled_order_voids_settlement(api):
    """PRD §3.6: "Cancelling advances `broadcast_status` to `CANCELLED`, sets
    `settlement_status` to `VOID`, and cascades every `HELD` or `CONFIRMED`
    venue booking of the order to `RELEASED`".

    Design: Difficulty/transitive_cascade/cancel_scheduled_order_cascades_booking_then_camera_release
    """
    base = _scheduled_order_with_assignment()
    order = transition_order(base["order"]["id"], "CANCEL")
    assert order["broadcast_status"] == "CANCELLED"
    assert order["settlement_status"] == "VOID"


# --- compensating_invariant: SCHEDULE consumes, CANCEL refunds the credit -----
def test_cancel_scheduled_order_sets_cancelled(api):
    """PRD §3.6: "Cancelling advances `broadcast_status` to `CANCELLED`, sets
    `settlement_status` to `VOID`, and cascades every `HELD` or `CONFIRMED`
    venue booking of the order to `RELEASED`".

    Design: Difficulty/compensating_invariant/cancel_scheduled_order_refunds_stream_credit
    """
    base = setup_scheduled_order(
        initial_credits=1,
        scheduled_start="2026-06-18T10:00:00Z", scheduled_end="2026-06-18T11:00:00Z",
    )
    order = transition_order(base["order"]["id"], "CANCEL")
    assert order["broadcast_status"] == "CANCELLED"


def test_cancel_scheduled_order_refunds_the_consumed_credit(api):
    """PRD §3.6: "When the order being cancelled was `SCHEDULED`, cancellation
    additionally refunds the one stream credit that scheduling consumed, adding
    one back to the home's `stream_credit_balance`".

    Design: Difficulty/compensating_invariant/cancel_scheduled_order_refunds_stream_credit
    """
    base = setup_scheduled_order(
        initial_credits=1,
        scheduled_start="2026-06-18T10:00:00Z", scheduled_end="2026-06-18T11:00:00Z",
    )
    assert get_home(base["home"]["id"])["stream_credit_balance"] == 0  # consumed at SCHEDULE
    transition_order(base["order"]["id"], "CANCEL")
    assert get_home(base["home"]["id"])["stream_credit_balance"] == 1  # refunded on CANCEL


# --- cross_entity_state_dependency: SCHEDULE needs a CONFIRMED booking --------
def _order_with_held_booking_and_ready_stream():
    """Order with a HELD (unconfirmed) booking, stream READY, 1 credit, DRAFT."""
    base = setup_draft_order(
        initial_credits=1,
        scheduled_start="2026-06-13T10:00:00Z", scheduled_end="2026-06-13T11:00:00Z",
    )
    booking = create_booking(
        base["order"]["id"], base["venue"]["id"],
        "2026-06-13T10:00:00Z", "2026-06-13T11:00:00Z", base["order"]["version"],
    )
    transition_order(base["order"]["id"], "SET_STREAM_READY")
    base["booking"] = booking
    return base


def test_schedule_with_held_booking_rejected(api):
    """PRD §3.6: "It requires, in order, that the order be in `DRAFT` (otherwise
    `ERR_ORDER_NOT_DRAFT`), that at least one venue booking of the order be
    `CONFIRMED` (otherwise `ERR_VENUE_NOT_CONFIRMED`)".

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_confirmed_venue_booking
    """
    base = _order_with_held_booking_and_ready_stream()
    resp = api.transition_service_order(base["order"]["id"], {"action": "SCHEDULE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VENUE_NOT_CONFIRMED)


def test_schedule_rejected_for_held_booking_leaves_order_draft(api):
    """PRD §3.6: "Scheduling advances `broadcast_status` from `DRAFT` to
    `SCHEDULED` and is the system's most heavily guarded transition."
    PRD §3.6: "that at least one venue booking of the order be `CONFIRMED`
    (otherwise `ERR_VENUE_NOT_CONFIRMED`)".

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_confirmed_venue_booking
    """
    base = _order_with_held_booking_and_ready_stream()
    api.transition_service_order(base["order"]["id"], {"action": "SCHEDULE"}, ADMIN)
    assert get_order(base["order"]["id"])["broadcast_status"] == "DRAFT"


# --- cross_entity_state_dependency: camera assignment needs ON_DUTY operator --
def test_assign_off_duty_operator_rejected(api):
    """PRD §3.5: "the target operator must be on duty; assigning an operator
    whose `duty_status` is not `ON_DUTY` is rejected with `ERR_OPERATOR_OFF_DUTY`."

    Design: Difficulty/cross_entity_state_dependency/camera_assignment_requires_operator_on_duty
    """
    base = setup_draft_order(
        scheduled_start="2026-06-14T10:00:00Z", scheduled_end="2026-06-14T11:00:00Z",
    )
    op = create_operator(base["home"]["id"], skill="AUDIO")  # default OFF_DUTY
    payload = create_camera_assignment_payload(base["order"]["id"], op["id"], "AUDIO")
    validate_error(api.create_camera_assignment(payload, ADMIN), ApiErrorId.ERR_OPERATOR_OFF_DUTY)


def test_assign_on_duty_operator_succeeds(api):
    """PRD §3.5: "An assignment names the `order_id`, the `operator_id`, and the
    crew `role` (one of `CAMERA`, `AUDIO`, or `SUPPORT`), copies the order's
    `home_id`, and starts in `ASSIGNED` status."

    Design: Difficulty/cross_entity_state_dependency/camera_assignment_requires_operator_on_duty
    """
    base = setup_draft_order(
        scheduled_start="2026-06-14T10:00:00Z", scheduled_end="2026-06-14T11:00:00Z",
    )
    op = create_operator(base["home"]["id"], skill="AUDIO")
    set_operator_duty(op["id"], "ON_DUTY")
    payload = create_camera_assignment_payload(base["order"]["id"], op["id"], "AUDIO")
    data = validate_success(api.create_camera_assignment(payload, ADMIN), 201)
    assert data["status"] == "ASSIGNED"


# --- resource_temporal_overlap: venue buffered conflict ----------------------
def _venue_with_booking_a(turnaround_minutes=30):
    """Venue with turnaround; order A booked 10:00-12:00 HELD. Returns base."""
    base = setup_home_and_venue(initial_credits=0, turnaround_minutes=turnaround_minutes)
    order_a = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="A One",
                           scheduled_start="2026-06-15T10:00:00Z",
                           scheduled_end="2026-06-15T12:00:00Z")
    create_booking(order_a["id"], base["venue"]["id"],
                   "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z", order_a["version"])
    base["order_a"] = order_a
    return base


def test_second_booking_within_turnaround_buffer_rejected(api):
    """PRD §3.4: "A new booking window is expanded by the venue's
    `turnaround_minutes` on both sides, and if that expanded window intersects
    any existing `HELD` or `CONFIRMED` booking on the same venue, the reservation
    is refused with `ERR_VENUE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/venue_booking_conflicts_within_turnaround_buffer
    """
    base = _venue_with_booking_a(turnaround_minutes=30)
    order_b = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="M Two",
                           scheduled_start="2026-06-15T12:15:00Z",
                           scheduled_end="2026-06-15T13:00:00Z")
    payload = create_venue_booking_payload(
        order_b["id"], base["venue"]["id"],
        "2026-06-15T12:15:00Z", "2026-06-15T13:00:00Z", order_b["version"],
    )
    validate_error(api.create_venue_booking(payload, ADMIN), ApiErrorId.ERR_VENUE_TIME_CONFLICT)


def test_second_booking_clear_of_turnaround_buffer_allowed(api):
    """PRD §3.4: "A new booking window is expanded by the venue's
    `turnaround_minutes` on both sides, and if that expanded window intersects
    any existing `HELD` or `CONFIRMED` booking on the same venue, the reservation
    is refused with `ERR_VENUE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/venue_booking_conflicts_within_turnaround_buffer
    """
    base = _venue_with_booking_a(turnaround_minutes=30)
    # 14:00 start is two hours past A's 12:00 end — expanded window (13:30-15:30)
    # cannot intersect [10:00,12:00], so the reservation is not a conflict.
    order_b = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="M Far",
                           scheduled_start="2026-06-15T14:00:00Z",
                           scheduled_end="2026-06-15T15:00:00Z")
    payload = create_venue_booking_payload(
        order_b["id"], base["venue"]["id"],
        "2026-06-15T14:00:00Z", "2026-06-15T15:00:00Z", order_b["version"],
    )
    data = validate_success(api.create_venue_booking(payload, ADMIN), 201)
    assert data["status"] == "HELD"


# --- resource_temporal_overlap: operator strict overlap, adjacency allowed ----
def _on_duty_operator_assigned_to_a():
    """ON_DUTY operator assigned to order A 10:00-12:00. Returns base with 'operator'."""
    base = setup_home_and_venue(initial_credits=0)
    op = create_operator(base["home"]["id"], skill="CAMERA")
    set_operator_duty(op["id"], "ON_DUTY")
    order_a = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="A One",
                           scheduled_start="2026-06-16T10:00:00Z",
                           scheduled_end="2026-06-16T12:00:00Z")
    create_assignment(order_a["id"], op["id"], "CAMERA")
    base["operator"] = op
    return base


def test_operator_adjacent_assignment_allowed(api):
    """PRD §3.5: "This overlap check is strict and applies no buffer; two windows
    that merely touch end-to-start are treated as non-overlapping and are allowed."

    Design: Difficulty/resource_temporal_overlap/operator_overlap_rejected_but_exact_adjacency_allowed
    """
    base = _on_duty_operator_assigned_to_a()
    order_b = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="B Two",
                           scheduled_start="2026-06-16T12:00:00Z",
                           scheduled_end="2026-06-16T13:00:00Z")
    payload = create_camera_assignment_payload(order_b["id"], base["operator"]["id"], "CAMERA")
    data = validate_success(api.create_camera_assignment(payload, ADMIN), 201)
    assert data["status"] == "ASSIGNED"


def test_operator_overlapping_assignment_rejected(api):
    """PRD §3.5: "the operator must be free during the service: an assignment
    covers its order's planned window from `scheduled_start` to `scheduled_end`,
    and if that window overlaps the window of any other `ASSIGNED` assignment for
    the same operator, the request is refused with `ERR_OPERATOR_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/operator_overlap_rejected_but_exact_adjacency_allowed
    """
    base = _on_duty_operator_assigned_to_a()
    order_c = create_order(base["home"]["id"], base["venue"]["id"], decedent_name="C Three",
                           scheduled_start="2026-06-16T11:30:00Z",
                           scheduled_end="2026-06-16T13:00:00Z")
    payload = create_camera_assignment_payload(order_c["id"], base["operator"]["id"], "CAMERA")
    validate_error(api.create_camera_assignment(payload, ADMIN),
                   ApiErrorId.ERR_OPERATOR_TIME_CONFLICT)


# --- Queue B: confirm already-confirmed booking; schedule with 0 credits ------
def test_confirm_already_confirmed_booking_rejected(api):
    """PRD §3.4: "A held booking becomes firm when the funeral home confirms it,
    moving its `status` from `HELD` to `CONFIRMED`; confirming anything not
    currently `HELD` is rejected with `ERR_BOOKING_NOT_HELD`."

    Design: Corner/state_machines/confirm_already_confirmed_booking_returns_not_held
    """
    base = setup_booking_confirmed_order(
        initial_credits=0,
        scheduled_start="2026-06-21T10:00:00Z", scheduled_end="2026-06-21T11:00:00Z",
    )
    resp = api.confirm_venue_booking(base["booking"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_HELD)


def test_schedule_with_zero_credits_rejected(api):
    """PRD §3.6: "and that the home's `stream_credit_balance` be at least one
    (otherwise `ERR_INSUFFICIENT_STREAM_CREDITS`)."

    Design: Corner/validations/schedule_insufficient_credits_returns_402
    """
    base = setup_booking_confirmed_order(
        initial_credits=0,
        scheduled_start="2026-06-22T10:00:00Z", scheduled_end="2026-06-22T11:00:00Z",
    )
    resp = api.transition_service_order(base["order"]["id"], {"action": "SCHEDULE"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STREAM_CREDITS)
