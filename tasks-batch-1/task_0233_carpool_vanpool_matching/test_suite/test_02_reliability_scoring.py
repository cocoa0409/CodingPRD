"""Reliability scoring and the reservation reliability gate (PRD §3.6, §3.8).

Covers confirmed vs provisional divergence, the no-show reliability cascade, the
late-cancel penalty, and the strict 70.0 floor admitting the exact boundary.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, create_trip, create_reservation,
    setup_rider_with_reliability,
)

PA = make_program_admin_headers()


def test_reliability_confirmed_excludes_provisional_pending_bonus(api):
    """PRD §3.8: "The persisted score — the one consulted by the reservation
    reliability gate of §3.6 — is the confirmed variant, counting only realized
    events."
    PRD §3.8: "it takes the persisted events and additionally treats each of the
    member's currently `RESERVED` (not yet ridden) reservations as an expected
    `COMPLETION` worth +2.0, summing those pending bonuses into the raw before the
    same clamp and one-decimal rounding."

    One realized NO_SHOW -> confirmed 85.0; one further RESERVED reservation adds a
    +2.0 provisional pending bonus -> provisional 87.0.

    Design: Difficulty/dual_variant_calc/reliability_provisional_vs_confirmed_diverges_on_pending
    """
    ctx = setup_rider_with_reliability(target_no_shows=1, api=api, rider_wallet=50000)
    prog_id, drv_id, rider_id = ctx["program_id"], ctx["driver_id"], ctx["rider_id"]

    # A fresh ACTIVE pool whose future trip the rider reserves (held RESERVED).
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_id, "plate": "VAN-2", "seat_capacity": 6},
        make_driver_headers(drv_id)))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": prog_id, "driver_member_id": drv_id, "vehicle_id": veh["id"],
         "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv_id)))
    get_success_data(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": rider_id, "expected_pool_version": pool["version"]},
        make_rider_headers(rider_id)))
    get_success_data(api.activate_pool(pool["id"], make_driver_headers(drv_id)))
    trip = create_trip(pool["id"], drv_id, api=api, departure_at="2026-08-01T15:00:00Z",
                       distance_miles=10.0)
    create_reservation(trip["id"], rider_id, trip["version"], api=api, seat_count=1)

    member = get_success_data(api.get_member(rider_id, PA))
    assert member["reliability_score"] == 85.0

    confirmed = validate_success(api.get_member_reliability(
        rider_id, make_rider_headers(rider_id), params={"mode": "confirmed"}))
    provisional = validate_success(api.get_member_reliability(
        rider_id, make_rider_headers(rider_id), params={"mode": "provisional"}))
    assert confirmed["reliability_score"] == 85.0
    assert provisional["reliability_score"] == 87.0
    assert provisional["reliability_score"] != confirmed["reliability_score"]


def test_no_show_cascade_recomputes_count_and_reliability(api):
    """PRD §3.5: "every reservation still in `RESERVED` at that moment is cascaded
    to `NO_SHOW`, and each such no-show runs the no-show side effects below."
    PRD §3.6: "Each no-show recomputes the member's `no_show_count`, appends a
    `ReliabilityEvent` of type `NO_SHOW`, recomputes the member's
    `reliability_score`, and recomputes the trip's `seats_reserved` as the seat is
    released."

    A single RESERVED rider departing yields no_show_count 1 and reliability 85.0
    (base 100 - 15 for one NO_SHOW).

    Design: Difficulty/transitive_cascade/no_show_cascade_depth3_reliability_recompute
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api, seat_count=1)
    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))
    get_success_data(api.depart_trip(trip["id"], make_driver_headers(drv_id)))

    res_after = get_success_data(api.get_reservation(res["id"], make_driver_headers(drv_id)))
    assert res_after["reservation_status"] == "NO_SHOW"
    member = get_success_data(api.get_member(rider["id"], PA))
    assert member["no_show_count"] == 1
    assert member["reliability_score"] == 85.0


def test_late_cancel_while_boarding_applies_reliability_penalty(api):
    """PRD §3.6: "a rider-initiated cancel that happens while the trip is already
    `BOARDING` is a late cancellation: it appends a `ReliabilityEvent` of type
    `LATE_CANCEL` and recomputes the rider's `reliability_score`."

    A LATE_CANCEL contributes -6.0, dropping a fresh rider from 100.0 to 94.0.

    Design: Corner/cross_cutting_complexity_layers/late_cancel_reliability_penalty_on_boarding
    """
    ctx = setup_active_pool(api=api, seed_rider_name="Rae", seed_rider_wallet=50000)
    drv_id, pool_id = ctx["driver_id"], ctx["pool_id"]
    rider = ctx["seed"]
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)
    res = create_reservation(trip["id"], rider["id"], trip["version"], api=api, seat_count=1)
    get_success_data(api.open_boarding_trip(trip["id"], make_driver_headers(drv_id)))

    cancelled = validate_success(api.cancel_reservation(res["id"], make_rider_headers(rider["id"])))
    assert cancelled["reservation_status"] == "CANCELLED"
    member = get_success_data(api.get_member(rider["id"], PA))
    assert member["reliability_score"] == 94.0


def test_reservation_admitted_at_exact_reliability_floor_of_seventy(api):
    """PRD §3.6: "A rider whose stored (confirmed) `reliability_score` is below 70.0
    may not create a new reservation and is turned away with
    `ERR_RELIABILITY_TOO_LOW`."

    Two realized NO_SHOWs leave reliability at exactly 70.0; the gate is strict
    (below 70.0 blocks) so the boundary reservation succeeds.

    Design: Difficulty/boundary_precision_check/reliability_floor_exact_70_admitted
    """
    ctx = setup_rider_with_reliability(target_no_shows=2, api=api, rider_wallet=50000)
    prog_id, drv_id, rider_id = ctx["program_id"], ctx["driver_id"], ctx["rider_id"]
    member = get_success_data(api.get_member(rider_id, PA))
    assert member["reliability_score"] == 70.0

    # Fresh pool + trip with a free seat for the boundary reservation.
    veh = get_success_data(api.create_vehicle(
        {"owner_member_id": drv_id, "plate": "VAN-OK", "seat_capacity": 6},
        make_driver_headers(drv_id)))
    pool = get_success_data(api.create_pool(
        {"employer_program_id": prog_id, "driver_member_id": drv_id, "vehicle_id": veh["id"],
         "kind": "VANPOOL", "origin_zone": "Z-N", "dest_zone": "Z-DT",
         "departure_days": ["MON", "TUE", "WED", "THU", "FRI"],
         "base_cost_cents": 2000, "per_mile_cents": 120}, make_driver_headers(drv_id)))
    get_success_data(api.create_membership(
        {"pool_id": pool["id"], "rider_member_id": rider_id, "expected_pool_version": pool["version"]},
        make_rider_headers(rider_id)))
    get_success_data(api.activate_pool(pool["id"], make_driver_headers(drv_id)))
    trip = create_trip(pool["id"], drv_id, api=api, departure_at="2026-09-01T15:00:00Z",
                       distance_miles=10.0)
    res = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": rider_id,
         "expected_trip_version": trip["version"], "seat_count": 1},
        make_rider_headers(rider_id)), expected_status=201)
    assert res["reservation_status"] == "RESERVED"
