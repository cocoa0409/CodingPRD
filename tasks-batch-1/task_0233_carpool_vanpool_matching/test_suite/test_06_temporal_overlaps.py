"""Temporal-overlap guards: trip-window collisions and rider double-booking
(PRD §3.5, §3.6).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, create_trip, create_reservation,
)

PA = make_program_admin_headers()


def test_overlapping_trip_window_on_same_pool_rejected(api):
    """PRD §3.5: "its travel window, the half-open interval from `departure_at` up to
    but not including `departure_at` plus `duration_min`, must not overlap the window
    of any non-`CANCELLED` trip of that pool, with no buffer applied; an overlap is
    rejected with `ERR_TRIP_WINDOW_OVERLAP`."

    First trip [15:00, 15:40); a second trip starting 15:39 (duration 40) overlaps.

    Design: Difficulty/resource_temporal_overlap/trip_window_half_open_no_buffer_on_pool
    """
    ctx = setup_active_pool(api=api)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    create_trip(pool_id, drv_id, api=api, departure_at="2026-06-09T15:00:00Z",
                duration_min=40, distance_miles=10.0)
    validate_error(api.create_trip(
        {"pool_id": pool_id, "departure_at": "2026-06-09T15:39:00Z",
         "duration_min": 40, "distance_miles": 10.0}, make_driver_headers(drv_id)),
        ApiErrorId.ERR_TRIP_WINDOW_OVERLAP.value)


def test_rider_double_booked_within_buffer_across_pools_rejected(api):
    """PRD §3.6: "the new reservation may not put the rider on two trips whose travel
    windows, each expanded on both sides by the rider buffer of fifteen minutes (a
    closed interval), overlap — a clash is rejected with `ERR_RIDER_DOUBLE_BOOKED`."

    A rider already on PoolA's [15:00, 15:40) trip is blocked from PoolB's
    [16:00, 16:40) trip: buffering each window by 15 min makes them conflict
    ([14:45, 15:55] vs [15:45, 16:55]) even though the raw intervals do not touch.

    Design: Difficulty/resource_temporal_overlap/rider_double_booked_buffered_closed_interval_on_member
    """
    program = get_success_data(api.create_employer_program(
        {"employer_name": "Acme", "hov_discount_pct": 0.50, "employer_match_pct": 0.30,
         "monthly_benefit_cap_cents": 100000, "grh_annual_cap_cents": 20000,
         "grh_per_event_cap_cents": 6000, "subsidy_budget_cents": 1000000}, PA))
    drv_a = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "DrvA", "home_zone": "Z-N",
         "work_zone": "Z-DT", "can_drive": True}, PA))
    drv_b = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "DrvB", "home_zone": "Z-N",
         "work_zone": "Z-DT", "can_drive": True}, PA))
    rider = get_success_data(api.create_member(
        {"employer_program_id": program["id"], "full_name": "Rae", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))

    def build_pool(driver, plate):
        veh = get_success_data(api.create_vehicle(
            {"owner_member_id": driver["id"], "plate": plate, "seat_capacity": 6},
            make_driver_headers(driver["id"])))
        pool = get_success_data(api.create_pool(
            {"employer_program_id": program["id"], "driver_member_id": driver["id"],
             "vehicle_id": veh["id"], "kind": "VANPOOL", "origin_zone": "Z-N",
             "dest_zone": "Z-DT", "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
             "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(driver["id"])))
        return pool

    pool_a = build_pool(drv_a, "VAN-A")
    pool_b = build_pool(drv_b, "VAN-B")
    get_success_data(api.create_membership(
        {"pool_id": pool_a["id"], "rider_member_id": rider["id"],
         "expected_pool_version": pool_a["version"]}, make_rider_headers(rider["id"])))
    get_success_data(api.create_membership(
        {"pool_id": pool_b["id"], "rider_member_id": rider["id"],
         "expected_pool_version": pool_b["version"]}, make_rider_headers(rider["id"])))
    get_success_data(api.activate_pool(pool_a["id"], make_driver_headers(drv_a["id"])))
    get_success_data(api.activate_pool(pool_b["id"], make_driver_headers(drv_b["id"])))

    trip_a = create_trip(pool_a["id"], drv_a["id"], api=api,
                         departure_at="2026-06-09T15:00:00Z", duration_min=40, distance_miles=10.0)
    trip_b = create_trip(pool_b["id"], drv_b["id"], api=api,
                         departure_at="2026-06-09T16:00:00Z", duration_min=40, distance_miles=10.0)
    create_reservation(trip_a["id"], rider["id"], trip_a["version"], api=api, seat_count=1)
    validate_error(api.create_reservation(
        {"trip_id": trip_b["id"], "rider_member_id": rider["id"],
         "expected_trip_version": trip_b["version"], "seat_count": 1},
        make_rider_headers(rider["id"])), ApiErrorId.ERR_RIDER_DOUBLE_BOOKED.value)
