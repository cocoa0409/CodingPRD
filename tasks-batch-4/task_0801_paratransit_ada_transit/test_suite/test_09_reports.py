"""Fleet on-time-performance report: the pinned sum-then-divide-then-round order
and the empty-fleet edge.

Queue A (Difficulty): combinatorial_formula / fleet OTP sum-then-divide-then-round.
Queue B (Corner): OTP empty-fleet zero-count edge.
"""
import pytest
from test_helpers import validate_success, TEST_USERS
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]


def _fleet_two_on_time_one_late(api):
    """One rider, three well-separated picked-up trips: two on-time (ZA), one 31 min late (ZB)."""
    th.set_clock(api, "2026-06-01T00:00:00Z")
    za = th.create_zone_a(api)
    zb = th.create_zone_b(api)
    rider = th.create_certified_rider(api)
    rid = rider["id"]

    def picked_up(zone, pickup_at, actual_at, wheelchair_lat, wheelchair_lng):
        run = th.create_run(api, za["id"] if zone == za else zb["id"])
        trip = th.create_offered_trip(api, rid, zone["id"], zone["id"],
                                      requested_pickup_at=pickup_at, proposed_pickup_at=pickup_at,
                                      pickup_lat=wheelchair_lat, pickup_lng=wheelchair_lng,
                                      dropoff_lat=wheelchair_lat, dropoff_lng=wheelchair_lng)
        th.accept_trip(api, trip["id"], rid, run["id"], run["version"])
        api.pickup_trip(trip["id"],
                        {"actual_pickup_at": actual_at, "actual_pickup_zone_id": zone["id"]}, DRIVER)
        return trip

    picked_up(za, "2026-06-05T09:00:00Z", "2026-06-05T09:00:00Z", 40.0, -74.0)   # on-time
    picked_up(za, "2026-06-05T12:00:00Z", "2026-06-05T12:00:00Z", 40.0, -74.0)   # on-time
    picked_up(zb, "2026-06-05T15:00:00Z", "2026-06-05T15:31:00Z", 40.05, -74.0)  # 31 min late


def test_otp_counts_pickups_fleet_wide(api):
    """PRD §3.8: "It returns `total_pickups` (the count of such trips), `on_time_pickups`
    (the count of those whose `on_time` is true), and `otp_pct`."

    Design: Difficulty/combinatorial_formula/fleet_otp_sum_then_divide_then_round_once_not_zone_average
    """
    _fleet_two_on_time_one_late(api)
    report = validate_success(api.on_time_performance(DISPATCHER))
    assert report["total_pickups"] == 3
    assert report["on_time_pickups"] == 2


def test_otp_pct_is_sum_then_divide_then_round_once(api):
    """PRD §3.8: "The percentage is computed by summing across all matching trips first,
    then dividing `on_time_pickups` by `total_pickups`, then multiplying by 100, and
    rounding that single result half-up to two decimal places; rounding each trip or run
    individually before averaging is not used."

    Design: Difficulty/combinatorial_formula/fleet_otp_sum_then_divide_then_round_once_not_zone_average
    """
    _fleet_two_on_time_one_late(api)
    report = validate_success(api.on_time_performance(DISPATCHER))
    assert report["otp_pct"] == pytest.approx(66.67, abs=0.001)


def test_otp_empty_fleet_reports_zero_counts(api):
    """PRD §3.8: "It returns `total_pickups` (the count of such trips), `on_time_pickups`
    (the count of those whose `on_time` is true), and `otp_pct`."

    (The PRD does not define `otp_pct` for a zero-denominator fleet, so only the two
    zero counts — which the PRD uniquely determines — are asserted.)

    Design: Corner/calculations/otp_report_empty_fleet_zero_pickups_edge
    """
    report = validate_success(api.on_time_performance(TEST_USERS["admin_headers"]))
    assert report["total_pickups"] == 0
    assert report["on_time_pickups"] == 0
