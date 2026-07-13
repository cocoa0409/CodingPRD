"""Dock loading-slot buffer geometry and the reattempt-ceiling boundary."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    book_dock_appointment_payload, reserve_window_payload,
    make_route,
    reserve_order_window, add_route_stop, book_appointment, dispatch, record_lead_attempt,
    setup_network, setup_refused_once, make_order,
    TEST_USERS,
)

PLANNER = TEST_USERS["dispatch_planner_headers"]
DOCK = TEST_USERS["dock_coordinator_headers"]


# --- Difficulty: dock appointment buffer-gap semantics ---

def _dock_with_booked_appt(api):
    net = setup_network(api)
    r1 = make_route(api, net["depot"]["id"], net["team"]["id"])
    book_appointment(api, r1["id"], net["dock"]["id"], appt_start_min=360, appt_end_min=420)
    r2 = make_route(api, net["depot"]["id"], net["team"]["id"])
    return {"dock": net["dock"], "route2": r2}


def test_dock_appointment_within_buffer_rejected(api):
    """PRD §3.4: "The booking is refused if any already-booked appointment on the
    same dock and date sits within the dock's buffer_min gap of the requested
    interval — that is, if the clear gap between the new interval and an existing
    booked interval is smaller than buffer_min, the request is rejected with
    ERR_DOCK_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/dock_appointment_buffer_overlap
    """
    ctx = _dock_with_booked_appt(api)  # existing 360-420, dock buffer_min 30
    # New 445-500: clear gap 420->445 = 25 min < 30 buffer.
    resp = api.book_dock_appointment(
        ctx["route2"]["id"],
        book_dock_appointment_payload(ctx["dock"]["id"], appt_start_min=445, appt_end_min=500),
        DOCK,
    )
    validate_error(resp, ApiErrorId.ERR_DOCK_SLOT_CONFLICT.value)


def test_dock_appointment_outside_buffer_allowed(api):
    """PRD §3.4: "if the clear gap between the new interval and an existing booked
    interval is smaller than buffer_min, the request is rejected with
    ERR_DOCK_SLOT_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/dock_appointment_buffer_overlap
    """
    ctx = _dock_with_booked_appt(api)  # existing 360-420, dock buffer_min 30
    # New 450-500: clear gap 420->450 = 30 min, not smaller than the 30 buffer.
    data = validate_success(
        api.book_dock_appointment(
            ctx["route2"]["id"],
            book_dock_appointment_payload(ctx["dock"]["id"], appt_start_min=450, appt_end_min=500),
            DOCK,
        ),
        expected_status=201,
    )
    assert data["status"] == "BOOKED"


# --- Difficulty: reattempt-ceiling boundary ---

def test_reschedule_below_reattempt_ceiling_succeeds(api):
    """PRD §3.3: "From REFUSED_RETRY, reserving a fresh window re-enters the
    scheduling loop and advances REFUSED_RETRY → SCHEDULED; this reschedule is
    allowed only while reattempt_count is strictly less than the ceiling of 2
    reattempts, otherwise ERR_MAX_REATTEMPTS."

    Design: Difficulty/boundary_precision_check/max_reattempts_count_boundary
    """
    ns = setup_refused_once(api)  # reattempt_count == 1 (< 2)
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    assert order["reattempt_count"] == 1
    rescheduled = validate_success(
        api.reserve_window(
            order["id"],
            reserve_window_payload(ns["team"]["id"], order["version"], service_date="2026-06-02"),
            PLANNER,
        ),
        expected_status=201,
    )
    assert rescheduled["status"] == "RESERVED"


def test_reschedule_at_reattempt_ceiling_rejected(api):
    """PRD §3.3: "this reschedule is allowed only while reattempt_count is strictly
    less than the ceiling of 2 reattempts, otherwise ERR_MAX_REATTEMPTS."

    Design: Difficulty/boundary_precision_check/max_reattempts_count_boundary
    """
    # First refusal cycle brings reattempt_count to 1.
    ns = setup_refused_once(api)
    order = validate_success(api.get_order(ns["order"]["id"], PLANNER))
    team_id = ns["team"]["id"]
    depot_id = ns["depot"]["id"]
    dock_id = ns["dock"]["id"]

    # Reschedule (allowed at count 1), route + dispatch on a second date, refuse again -> count 2.
    w2 = reserve_order_window(api, order["id"], team_id, service_date="2026-06-02")
    r2 = make_route(api, depot_id, team_id, service_date="2026-06-02")
    add_route_stop(api, r2["id"], order["id"], w2["id"])
    book_appointment(api, r2["id"], dock_id, appt_date="2026-06-02")
    dispatch(api, r2["id"])
    record_lead_attempt(api, order["id"], team_id, "REFUSED", refusal_reason="attempt 2 refused")

    at_ceiling = validate_success(api.get_order(order["id"], PLANNER))
    assert at_ceiling["reattempt_count"] == 2

    # Third reschedule at reattempt_count == 2 is refused.
    resp = api.reserve_window(
        order["id"],
        reserve_window_payload(team_id, at_ceiling["version"], service_date="2026-06-03"),
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_MAX_REATTEMPTS.value)
