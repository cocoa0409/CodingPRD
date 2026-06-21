"""Bus trip lifecycle: ETA dual-variant, stop-to-stop self-loop, the incident fork,
onboard-count conservation, and driver-availability conservation.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    setup_boarding_trip,
    setup_boarding_trip_with_approved_rider,
    setup_scheduled_trip,
    make_admin_headers,
    make_driver_headers,
    ETA_STOP_FALLBACK_MIN,
    ETA_GPS_MIN,
)

ADMIN = make_admin_headers()


# ===========================================================================
# Difficulty/dual_variant_calc/eta_estimate_gps_vs_stop_fallback_diverge
# ===========================================================================
def _build_two_stop_boarding_for_eta(api):
    """Design ETA scenario: stops seq1@(40.0,-75.0), seq2@(40.01,-75.0); boarding."""
    district = get_success_data(api.create_district(
        {"name": "D1", "school_lat": 40.0, "school_lng": -75.0,
         "walk_threshold_miles": 1.5}, ADMIN))
    route = get_success_data(api.create_route(
        {"district_id": district["id"], "name": "R1",
         "seat_capacity": 20, "wheelchair_capacity": 2}, ADMIN))
    get_success_data(api.create_stop(
        {"route_id": route["id"], "label": "S1", "lat": 40.0, "lng": -75.0,
         "sequence": 1, "scheduled_departure": "2026-09-01T07:00:00Z"}, ADMIN))
    get_success_data(api.create_stop(
        {"route_id": route["id"], "label": "S2", "lat": 40.01, "lng": -75.0,
         "sequence": 2, "scheduled_departure": "2026-09-01T07:10:00Z"}, ADMIN))
    driver = get_success_data(api.create_driver(
        {"district_id": district["id"], "full_name": "Drv A"}, ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    assignment = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": assignment["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    get_success_data(api.start_boarding(trip["id"], drv))
    return trip, drv


def test_eta_stop_based_fallback_before_gps_ping(api):
    """PRD §3.6: "before any ping has arrived but while the trip is `BOARDING` or `IN_TRANSIT`, the origin is the coordinates of the previously departed stop, or the campus for the first stop, with the same speed constant applied."

    Design: Difficulty/dual_variant_calc/eta_estimate_gps_vs_stop_fallback_diverge
    """
    # Depart stop 1 -> IN_TRANSIT at seq2, no GPS ping yet => stop_based_fallback
    # ETA measured from the just-departed stop 1 to seq2 = 1.7 min.
    trip, drv = _build_two_stop_boarding_for_eta(api)
    departed = validate_success(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv), 200)
    assert departed["status"] == "IN_TRANSIT"
    assert departed["eta_next_stop_minutes"] == ETA_STOP_FALLBACK_MIN, (
        f"stop-based-fallback ETA must be {ETA_STOP_FALLBACK_MIN} before any ping, "
        f"got {departed['eta_next_stop_minutes']}"
    )


def test_eta_gps_based_diverges_from_stop_fallback(api):
    """PRD §3.6: "once a GPS ping has been recorded (the trip's `last_lat` and `last_lng` are set), the origin is those actual last-ping coordinates"
    PRD §3.6: "divides that distance by an assumed average speed of 25.0 miles per hour, multiplies by 60 to convert hours to minutes, and rounds the result half-up to one decimal place."

    Design: Difficulty/dual_variant_calc/eta_estimate_gps_vs_stop_fallback_diverge
    """
    # Build the exact design scenario: stops seq1@(40.0,-75.0), seq2@(40.01,-75.0).
    trip, drv = _build_two_stop_boarding_for_eta(api)
    # Depart stop 1: stop_based_fallback ETA to seq2 from stop1 = 1.7 min.
    departed = validate_success(
        api.depart_stop(trip["id"], {"stop_sequence": 1}, drv), 200
    )
    assert departed["eta_next_stop_minutes"] == ETA_STOP_FALLBACK_MIN, (
        f"stop-based-fallback ETA must be {ETA_STOP_FALLBACK_MIN}, "
        f"got {departed['eta_next_stop_minutes']}"
    )
    # GPS ping at (40.005,-75.0): gps_based ETA to seq2 = 0.8 min.
    pinged = validate_success(
        api.gps_ping(trip["id"], {"lat": 40.005, "lng": -75.0}, drv), 200
    )
    assert pinged["eta_next_stop_minutes"] == ETA_GPS_MIN, (
        f"gps-based ETA must be {ETA_GPS_MIN}, got {pinged['eta_next_stop_minutes']}"
    )
    assert ETA_STOP_FALLBACK_MIN != ETA_GPS_MIN, (
        "the two variants must diverge on the same trip and target stop"
    )


# ===========================================================================
# Difficulty/non_linear_state_machine/bus_trip_in_transit_self_loop_and_incident_fork
# ===========================================================================
def _build_three_stop_in_transit_at_seq2(api):
    """District + route + 3 stops + boarding trip, departed stop1 -> IN_TRANSIT @ seq2."""
    district = get_success_data(api.create_district(
        {"name": "D1", "school_lat": 40.0, "school_lng": -75.0}, ADMIN))
    route = get_success_data(api.create_route(
        {"district_id": district["id"], "name": "R1", "seat_capacity": 20}, ADMIN))
    for i, lat in enumerate([40.0, 40.01, 40.02]):
        get_success_data(api.create_stop(
            {"route_id": route["id"], "label": f"S{i+1}", "lat": lat, "lng": -75.0,
             "sequence": i + 1,
             "scheduled_departure": f"2026-09-01T07:{i}0:00Z"}, ADMIN))
    driver = get_success_data(api.create_driver(
        {"district_id": district["id"], "full_name": "Drv A"}, ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    assignment = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": assignment["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    get_success_data(api.start_boarding(trip["id"], drv))
    get_success_data(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv))
    return district, route, driver, trip, drv


def test_in_transit_self_loop_advances_current_stop(api):
    """PRD §3.6: "each subsequent departure is a self-loop that keeps the trip `IN_TRANSIT`, permitted only while the current stop is not the route's final stop."
    PRD §3.6: "On every departure, `current_stop_sequence` advances to the next stop's sequence on the route (the smallest sequence strictly greater than the current one), and `eta_next_stop_minutes` is recomputed."

    Design: Difficulty/non_linear_state_machine/bus_trip_in_transit_self_loop_and_incident_fork
    """
    _, _, driver, trip, drv = _build_three_stop_in_transit_at_seq2(api)
    looped = validate_success(api.depart_stop(trip["id"], {"stop_sequence": 2}, drv), 200)
    assert looped["status"] == "IN_TRANSIT", "self-loop keeps the trip IN_TRANSIT"
    assert looped["current_stop_sequence"] == 3, (
        f"current_stop_sequence must advance 2 -> 3, got {looped['current_stop_sequence']}"
    )


def test_incident_fork_preserves_trip_progress(api):
    """PRD §3.7: "From either `BOARDING` or `IN_TRANSIT`, the acting `Driver` may raise an incident, moving the trip to `INCIDENT_HOLD`."
    PRD §3.7: "Raising an incident increments the trip's `incident_count` by one, recomputes the route's `open_incident` flag to true, and appends a parent notification of kind `INCIDENT` for every student currently onboard the bus."
    PRD §3.7: "A `TransportAdmin` later clears the incident, returning the trip from `INCIDENT_HOLD` to `IN_TRANSIT` and recomputing the route's `open_incident` flag, which becomes false only when no other `INCIDENT_HOLD` trip remains on the route."

    Design: Difficulty/non_linear_state_machine/bus_trip_in_transit_self_loop_and_incident_fork
    """
    _, _, driver, trip, drv = _build_three_stop_in_transit_at_seq2(api)
    looped = validate_success(api.depart_stop(trip["id"], {"stop_sequence": 2}, drv), 200)
    assert looped["current_stop_sequence"] == 3

    held = validate_success(api.raise_incident(trip["id"], drv), 200)
    assert held["status"] == "INCIDENT_HOLD"
    assert held["incident_count"] == 1, "raising an incident increments incident_count"

    cleared = validate_success(api.clear_incident(trip["id"], ADMIN), 200)
    assert cleared["status"] == "IN_TRANSIT", "clear-incident returns to IN_TRANSIT"
    assert cleared["current_stop_sequence"] == 3, (
        "trip progress (current_stop_sequence) is preserved across the incident fork"
    )


# ===========================================================================
# Difficulty/compensating_invariant/tap_on_then_off_conserves_onboard_count
# ===========================================================================
def test_tap_on_then_off_conserves_onboard_count(api):
    """PRD §3.6: "each `TAP_ON` adds the student to the onboard set and each `TAP_OFF` removes them, and the resulting set size is the count."

    Design: Difficulty/compensating_invariant/tap_on_then_off_conserves_onboard_count
    """
    district, route, stops, driver, assignment, trip, student, application = (
        setup_boarding_trip_with_approved_rider(num_stops=2, rfid_uid="RF-R")
    )
    drv = make_driver_headers(driver["id"])
    # TAP_ON at stop 1 -> onboard_count == 1.
    validate_success(
        api.record_tap(trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_ON",
                                    "stop_sequence": 1}, drv), 201)
    after_on = validate_success(api.get_bus_trip(trip["id"], drv), 200)
    assert after_on["onboard_count"] == 1, "onboard_count is 1 after TAP_ON"
    # Advance to stop 2, then compensating TAP_OFF -> onboard_count back to 0.
    get_success_data(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv))
    validate_success(
        api.record_tap(trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_OFF",
                                    "stop_sequence": 2}, drv), 201)
    after_off = validate_success(api.get_bus_trip(trip["id"], drv), 200)
    assert after_off["onboard_count"] == 0, (
        "compensating TAP_OFF conserves onboard_count back to its pre-tap value (0)"
    )


def test_onboard_count_zero_enables_completion(api):
    """PRD §3.6: "the driver completes the trip, which is legal only from `IN_TRANSIT`, only when `current_stop_sequence` equals the route's final stop sequence, and only when `onboard_count` is exactly 0 — a trip with riders still aboard is rejected with `ERR_RIDERS_STILL_ONBOARD`."

    Design: Difficulty/compensating_invariant/tap_on_then_off_conserves_onboard_count
    """
    district, route, stops, driver, assignment, trip, student, application = (
        setup_boarding_trip_with_approved_rider(num_stops=2, rfid_uid="RF-R")
    )
    drv = make_driver_headers(driver["id"])
    validate_success(
        api.record_tap(trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_ON",
                                    "stop_sequence": 1}, drv), 201)
    get_success_data(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv))
    # Compensating TAP_OFF returns onboard_count to 0, satisfying the completion guard.
    validate_success(
        api.record_tap(trip["id"], {"rfid_uid": "RF-R", "direction": "TAP_OFF",
                                    "stop_sequence": 2}, drv), 201)
    completed = validate_success(api.complete_trip(trip["id"], drv), 200)
    assert completed["status"] == "COMPLETED", (
        "completion is allowed once the conserved onboard_count returns to 0"
    )


# ===========================================================================
# Difficulty/compensating_invariant/board_then_complete_conserves_driver_availability
# ===========================================================================
def test_board_sets_driver_on_duty(api):
    """PRD §3.6: "On success the trip moves from `SCHEDULED` to `BOARDING`, `current_stop_sequence` is set to 1 (the first stop), and the driver's `status` becomes `ON_DUTY`."

    Design: Difficulty/compensating_invariant/board_then_complete_conserves_driver_availability
    """
    district = get_success_data(api.create_district(
        {"name": "D1", "school_lat": 40.0, "school_lng": -75.0}, ADMIN))
    route = get_success_data(api.create_route(
        {"district_id": district["id"], "name": "R1", "seat_capacity": 20}, ADMIN))
    for i, lat in enumerate([40.0, 40.01]):
        get_success_data(api.create_stop(
            {"route_id": route["id"], "label": f"S{i+1}", "lat": lat, "lng": -75.0,
             "sequence": i + 1,
             "scheduled_departure": f"2026-09-01T07:{i}0:00Z"}, ADMIN))
    driver = get_success_data(api.create_driver(
        {"district_id": district["id"], "full_name": "Drv A"}, ADMIN))
    assert driver["status"] == "AVAILABLE"
    route = get_success_data(api.get_route(route["id"], ADMIN))
    assignment = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": assignment["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    validate_success(api.start_boarding(trip["id"], drv), 200)
    on_duty = validate_success(api.get_driver(driver["id"], ADMIN), 200)
    assert on_duty["status"] == "ON_DUTY", "driver becomes ON_DUTY on start-boarding"


def test_complete_returns_driver_to_available(api):
    """PRD §3.6: "Completion moves the trip to `COMPLETED`, sets `eta_next_stop_minutes` to null, and returns the driver to `AVAILABLE`."

    Design: Difficulty/compensating_invariant/board_then_complete_conserves_driver_availability
    """
    district = get_success_data(api.create_district(
        {"name": "D1", "school_lat": 40.0, "school_lng": -75.0}, ADMIN))
    route = get_success_data(api.create_route(
        {"district_id": district["id"], "name": "R1", "seat_capacity": 20}, ADMIN))
    for i, lat in enumerate([40.0, 40.01]):
        get_success_data(api.create_stop(
            {"route_id": route["id"], "label": f"S{i+1}", "lat": lat, "lng": -75.0,
             "sequence": i + 1,
             "scheduled_departure": f"2026-09-01T07:{i}0:00Z"}, ADMIN))
    driver = get_success_data(api.create_driver(
        {"district_id": district["id"], "full_name": "Drv A"}, ADMIN))
    route = get_success_data(api.get_route(route["id"], ADMIN))
    assignment = get_success_data(api.create_driver_assignment(
        route["id"],
        {"driver_id": driver["id"], "role": "PRIMARY",
         "expected_route_version": route["version"]}, ADMIN))
    trip = get_success_data(api.create_bus_trip(
        {"route_id": route["id"], "driver_assignment_id": assignment["id"]}, ADMIN))
    drv = make_driver_headers(driver["id"])
    validate_success(api.start_boarding(trip["id"], drv), 200)
    # Depart stop 1 -> IN_TRANSIT at final stop (seq 2), onboard_count 0 (no taps).
    validate_success(api.depart_stop(trip["id"], {"stop_sequence": 1}, drv), 200)
    validate_success(api.complete_trip(trip["id"], drv), 200)
    final = validate_success(api.get_driver(driver["id"], ADMIN), 200)
    assert final["status"] == "AVAILABLE", (
        "driver availability is conserved back to its pre-trip AVAILABLE baseline"
    )
