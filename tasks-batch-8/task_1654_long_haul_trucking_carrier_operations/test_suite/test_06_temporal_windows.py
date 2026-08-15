"""Temporal ordering and overlap rules: half-open driver trip windows,
closed fuel-rate windows, half-open settlement periods, and monotonic event
streams (PRD §2.9, §3.1, §3.3, §3.4, §3.9)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_driver,
    create_fuel_rate,
    create_tractor,
    make_dispatcher_headers,
    make_driver_headers,
    make_load_planner_headers,
    plan_trip,
    post_duty_event,
    set_clock,
    setup_planned_trip,
    tender_load,
    create_settlement_for,
    validate_error,
    validate_success,
)

DISPATCHER = make_dispatcher_headers()
LOAD_PLANNER = make_load_planner_headers()

ROUTE_TX = [{"state_code": "TX", "miles": 1020}]


def _trip_payload(load_id, driver_id, tractor_id, start):
    return {"load_id": load_id, "driver_id": driver_id,
            "tractor_id": tractor_id, "planned_deadhead_miles": 120,
            "planned_start_at": start, "route_states": ROUTE_TX}


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / driver_trip_window_half_open_adjacency
# ---------------------------------------------------------------------------

def test_adjacent_trip_windows_allowed(api):
    """PRD §3.3: "Finally, the new trip's working window — the half-open
    interval from `planned_start_at` up to but not including the load's
    `delivery_appt_at` — must not intersect the corresponding window of any
    other non-terminal trip the driver holds; intersection is rejected with
    `ERR_TRIP_OVERLAP`, while two trips that merely touch at a boundary, one
    ending exactly when the other begins, do not overlap and are allowed."

    Design: Difficulty/resource_temporal_overlap/driver_trip_window_half_open_adjacency
    """
    ctx = setup_planned_trip(last_home_at="2026-07-28T00:00:00Z",
                             cdl_number="CDL-15", unit_number="T-17")
    driver = ctx["driver"]
    # trip1 window: [2026-08-02T06:00Z, 2026-08-03T18:00Z)
    load2 = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                        pickup_appt_at="2026-08-04T08:00:00Z",
                        delivery_appt_at="2026-08-05T18:00:00Z")
    validate_success(api_client.screen_load(load2["id"], LOAD_PLANNER))
    validate_success(api_client.accept_load(load2["id"], LOAD_PLANNER))
    tr2 = create_tractor(unit_number="T-18")
    # starts exactly when trip1's window ends: adjacent, allowed
    trip2 = plan_trip(load2["id"], driver["id"], tr2["id"],
                      planned_start_at="2026-08-03T18:00:00Z")
    assert trip2["status"] == "PLANNED"


def test_one_minute_earlier_trip_window_overlaps(api):
    """PRD §3.3: "intersection is rejected with `ERR_TRIP_OVERLAP`, while two
    trips that merely touch at a boundary, one ending exactly when the other
    begins, do not overlap and are allowed."
    (One minute before the boundary intersects the half-open window.)

    Design: Difficulty/resource_temporal_overlap/driver_trip_window_half_open_adjacency
    """
    ctx = setup_planned_trip(last_home_at="2026-07-28T00:00:00Z",
                             cdl_number="CDL-15", unit_number="T-17")
    driver = ctx["driver"]
    load3 = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                        pickup_appt_at="2026-08-04T08:00:00Z",
                        delivery_appt_at="2026-08-05T18:00:00Z")
    validate_success(api_client.screen_load(load3["id"], LOAD_PLANNER))
    validate_success(api_client.accept_load(load3["id"], LOAD_PLANNER))
    tr3 = create_tractor(unit_number="T-19")
    resp = api_client.create_trip(
        _trip_payload(load3["id"], driver["id"], tr3["id"],
                      "2026-08-03T17:59:00Z"),
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TRIP_OVERLAP)


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict / safety_beats_temporal_on_trip_create
# ---------------------------------------------------------------------------

def test_safety_gate_beats_overlap_when_both_fail(api):
    """PRD §2.9: "Every request is evaluated against a fixed, ordered pipeline
    of checks, and a failure at any stage short-circuits the stages after it.
    The order matters because it determines which error a doubly-invalid
    request produces." (Safety and regulatory gates are stage 8; temporal
    ordering and overlap is stage 9.)
    PRD §3.4: "If any clause fails, the create or replan is rejected with
    `ERR_HOS_INSUFFICIENT` (HTTP 422)."
    (Driver has 660 driving minutes since 06:00 -> drive_11h remaining 0; the
    requested window also overlaps trip1 — the HOS error must win.)

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_trip_create
    """
    ctx = setup_planned_trip(cdl_number="CDL-10", unit_number="T-10")
    driver = ctx["driver"]
    post_duty_event(driver["id"], event_type="DRIVING",
                    occurred_at="2026-08-01T06:00:00Z")
    set_clock("2026-08-01T17:00:00Z")
    post_duty_event(driver["id"], event_type="OFF_DUTY",
                    occurred_at="2026-08-01T17:00:00Z")

    load2 = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                        pickup_appt_at="2026-08-03T08:00:00Z",
                        delivery_appt_at="2026-08-04T18:00:00Z")
    validate_success(api_client.screen_load(load2["id"], LOAD_PLANNER))
    validate_success(api_client.accept_load(load2["id"], LOAD_PLANNER))
    tr2 = create_tractor(unit_number="T-11")
    resp = api_client.create_trip(
        _trip_payload(load2["id"], driver["id"], tr2["id"],
                      "2026-08-03T06:00:00Z"),
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_HOS_INSUFFICIENT)


def test_overlap_rejected_when_hos_clean(api):
    """PRD §3.3: "the new trip's working window — the half-open interval from
    `planned_start_at` up to but not including the load's `delivery_appt_at` —
    must not intersect the corresponding window of any other non-terminal trip
    the driver holds; intersection is rejected with `ERR_TRIP_OVERLAP`".
    (Fresh driver: every stage-8 gate passes, so the overlap surfaces alone.)

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_trip_create
    """
    ctx = setup_planned_trip(cdl_number="CDL-10", unit_number="T-10")
    load2 = tender_load(ctx["customer"]["id"], ctx["lane"]["id"],
                        pickup_appt_at="2026-08-03T08:00:00Z",
                        delivery_appt_at="2026-08-04T18:00:00Z")
    validate_success(api_client.screen_load(load2["id"], LOAD_PLANNER))
    validate_success(api_client.accept_load(load2["id"], LOAD_PLANNER))
    tr2 = create_tractor(unit_number="T-11")
    resp = api_client.create_trip(
        _trip_payload(load2["id"], ctx["driver"]["id"], tr2["id"],
                      "2026-08-03T06:00:00Z"),
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_TRIP_OVERLAP)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / fuel_rate_closed_window_touch_conflicts
# ---------------------------------------------------------------------------

def test_touching_fuel_rate_windows_conflict(api):
    """PRD §3.1: "Because the windows are closed intervals, two windows for the
    same `state_code` conflict whenever the new window starts on or before the
    existing window's end (or the existing window is open-ended) and the new
    window's end is open or falls on or after the existing window's start —
    even windows that merely touch at an endpoint conflict, and the create is
    rejected with `ERR_FUEL_RATE_WINDOW_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/fuel_rate_closed_window_touch_conflicts
    """
    set_clock("2026-08-01T06:00:00Z")
    create_fuel_rate(state_code="TX", tax_cents_per_gallon=20,
                     avg_pump_price_cents=400,
                     effective_from="2026-01-01T00:00:00Z",
                     effective_to="2026-12-31T00:00:00Z")
    resp = api_client.create_state_fuel_rate(
        {"state_code": "TX", "tax_cents_per_gallon": 22,
         "avg_pump_price_cents": 410,
         "effective_from": "2026-12-31T00:00:00Z"},
        {"X-User-ID": "fleet-admin-1", "X-User-Role": "FleetAdmin"})
    validate_error(resp, ApiErrorId.ERR_FUEL_RATE_WINDOW_OVERLAP)


def test_one_second_gap_between_windows_allowed(api):
    """PRD §3.1: "effective over a closed window from `effective_from` through
    `effective_to`, both endpoints inclusive" — a window starting one second
    after the existing window's end is disjoint and must be created.
    PRD §3.1: "even windows that merely touch at an endpoint conflict, and the
    create is rejected with `ERR_FUEL_RATE_WINDOW_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/fuel_rate_closed_window_touch_conflicts
    """
    set_clock("2026-08-01T06:00:00Z")
    create_fuel_rate(state_code="TX", tax_cents_per_gallon=20,
                     avg_pump_price_cents=400,
                     effective_from="2026-01-01T00:00:00Z",
                     effective_to="2026-12-31T00:00:00Z")
    created = validate_success(api_client.create_state_fuel_rate(
        {"state_code": "TX", "tax_cents_per_gallon": 22,
         "avg_pump_price_cents": 410,
         "effective_from": "2026-12-31T00:00:01Z"},
        {"X-User-ID": "fleet-admin-1", "X-User-Role": "FleetAdmin"}),
        expected_status=201)
    assert created["state_code"] == "TX"


def test_settlement_period_overlap_half_open(api):
    """PRD §3.9: "The period is the half-open interval from `period_start`
    inclusive to `period_end` exclusive, and it must not intersect any existing
    settlement period for the same driver; an intersection is rejected with
    `ERR_SETTLEMENT_PERIOD_OVERLAP`, while two periods that merely touch, one
    ending exactly where the next begins, do not overlap and are allowed."

    Design: Corner/validations/settlement_period_overlap_half_open
    """
    set_clock("2026-08-01T06:00:00Z")
    driver = create_driver(cdl_number="CDL-V7")
    create_settlement_for(driver["id"])
    resp = api_client.create_settlement(
        {"driver_id": driver["id"], "period_start": "2026-08-05T00:00:00Z",
         "period_end": "2026-08-12T00:00:00Z"},
        {"X-User-ID": "payroll-1", "X-User-Role": "PayrollClerk"})
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_PERIOD_OVERLAP)
    adjacent = create_settlement_for(driver["id"],
                                     period_start="2026-08-08T00:00:00Z",
                                     period_end="2026-08-15T00:00:00Z")
    assert adjacent["status"] == "DRAFT"


def test_duty_event_strictly_increasing_enforced(api):
    """PRD §3.4: "An `occurred_at` after the logical now fails request
    validation with `ERR_INVALID_REQUEST`; one that does not fall strictly
    after the driver's previous event is rejected with
    `ERR_DUTY_EVENT_OUT_OF_ORDER`, so the stream is strictly increasing in
    time by construction."

    Design: Corner/state_machines/duty_event_monotonic_time_enforced
    """
    # Clock is placed at 07:00 so every event below is at or before the
    # logical now (PRD §3.4 future-timestamp rejection must not pre-empt the
    # strictly-increasing rule under test).
    set_clock("2026-08-01T07:00:00Z")
    driver = create_driver(cdl_number="CDL-C25")
    post_duty_event(driver["id"], event_type="OFF_DUTY",
                    occurred_at="2026-08-01T06:00:00Z")
    resp = api_client.create_duty_event(
        driver["id"], {"event_type": "ON_DUTY",
                       "occurred_at": "2026-08-01T06:00:00Z"},
        make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_DUTY_EVENT_OUT_OF_ORDER)
    later = post_duty_event(driver["id"], event_type="ON_DUTY",
                            occurred_at="2026-08-01T06:01:00Z")
    assert later["event_type"] == "ON_DUTY"


def test_duty_event_after_default_clock_rejected(api):
    """PRD §2.4: "At startup, before any clock-setting call has been made, the
    logical time is exactly 2026-08-01T00:00:00Z, and the server must never
    fall back to wall-clock time in lieu of an explicit set."
    PRD §3.4: "An `occurred_at` after the logical now fails request validation
    with `ERR_INVALID_REQUEST`".
    (The clock is deliberately never set in this test.)

    Design: Corner/state_machines/duty_event_future_rejected_uses_default_clock
    """
    driver = create_driver(cdl_number="CDL-C26")
    resp = api_client.create_duty_event(
        driver["id"], {"event_type": "DRIVING",
                       "occurred_at": "2026-08-02T00:00:00Z"},
        make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    past = post_duty_event(driver["id"], event_type="OFF_DUTY",
                           occurred_at="2026-07-31T23:59:00Z")
    assert past["event_type"] == "OFF_DUTY"
