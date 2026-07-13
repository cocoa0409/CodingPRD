"""Fare computation: same-zone vs cross-zone base, the ADA 2x cap, companion
charges, and the provisional/final dual-variant divergence.

Queue A (Difficulty): dual_variant_calc (fare), combinatorial_formula (fare).
Queue B (Corner): calculations / cross-zone cap-binding fare.
"""
from test_helpers import validate_success, TEST_USERS
import test_helpers as th

DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]


def _rider_two_zones_run(api, seats=4):
    """Certified rider + ZA + ZB + run in ZA. Returns dict with rider, zone_a, zone_b, run."""
    th.set_clock(api, "2026-06-01T00:00:00Z")
    zone_a = th.create_zone_a(api)
    zone_b = th.create_zone_b(api)
    rider = th.create_certified_rider(api)
    run = th.create_run(api, zone_a["id"], seats=seats, positions=2)
    return {"rider": rider, "zone_a": zone_a, "zone_b": zone_b, "run": run}


# ==========================================================================
# Difficulty A — dual_variant_calc: provisional vs final fare divergence
# ==========================================================================
def _same_zone_accepted_then_dropoff_in_zb(api):
    """Trip requested same-zone ZA->ZA, accepted (estimated), then dropped off in ZB (final)."""
    ctx = _rider_two_zones_run(api)
    rider_id = ctx["rider"]["id"]
    za, zb = ctx["zone_a"]["id"], ctx["zone_b"]["id"]
    trip = th.create_offered_trip(api, rider_id, za, za)
    th.accept_trip(api, trip["id"], rider_id, ctx["run"]["id"], ctx["run"]["version"])
    api.pickup_trip(trip["id"],
                    {"actual_pickup_at": "2026-06-05T09:00:00Z", "actual_pickup_zone_id": za}, DRIVER)
    validate_success(api.dropoff_trip(
        trip["id"], {"actual_dropoff_at": "2026-06-05T09:20:00Z", "actual_dropoff_zone_id": zb}, DRIVER))
    return validate_success(api.get_trip(trip["id"], DRIVER))


def test_provisional_fare_uses_requested_same_zone(api):
    """PRD §3.8: "when the pickup zone and the dropoff zone are the same zone, the base
    equals that zone's `base_fare_cents`."
    PRD §3.8: "a provisional fare at accept, stored in `estimated_fare_cents` and priced
    from the trip's requested `pickup_zone_id` and `dropoff_zone_id`."

    Design: Difficulty/dual_variant_calc/trip_fare_provisional_vs_final_diverge_on_actual_dropoff_zone
    """
    trip = _same_zone_accepted_then_dropoff_in_zb(api)
    assert trip["estimated_fare_cents"] == 500
    assert trip["status"] == "COMPLETED"


def test_final_fare_uses_actual_dropoff_zone_and_diverges(api):
    """PRD §3.8: "a final fare at dropoff, stored in `final_fare_cents` and priced from
    the actual `actual_pickup_zone_id` and `actual_dropoff_zone_id`."
    PRD §3.8: "Because the final variant uses the actual dropoff zone, the final fare may
    differ from the provisional one when the actual dropoff zone differs from the
    requested one."

    Design: Difficulty/dual_variant_calc/trip_fare_provisional_vs_final_diverge_on_actual_dropoff_zone
    """
    trip = _same_zone_accepted_then_dropoff_in_zb(api)
    assert trip["final_fare_cents"] == 580
    assert trip["final_fare_cents"] != trip["estimated_fare_cents"]


# ==========================================================================
# Difficulty A — combinatorial_formula: cross-zone cap binds, then companions add
# ==========================================================================
def _cross_zone_two_companions_accepted(api):
    ctx = _rider_two_zones_run(api)
    rider_id = ctx["rider"]["id"]
    za, zb = ctx["zone_a"]["id"], ctx["zone_b"]["id"]
    trip = th.create_offered_trip(api, rider_id, za, zb,
                                  dropoff_lat=40.05, dropoff_lng=-74.0, num_companions=2)
    resp = th.accept_trip(api, trip["id"], rider_id, ctx["run"]["id"], ctx["run"]["version"])
    validate_success(resp, 200)
    return validate_success(api.get_trip(trip["id"], DISPATCHER))


def test_cross_zone_cap_binds_then_companions_added(api):
    """PRD §3.8: "otherwise the base equals the greater of the pickup zone's
    `base_fare_cents` and the dropoff zone's `base_fare_cents`, plus a cross-zone
    surcharge of 150 cents. That base is then capped at the ADA ceiling: the capped
    amount is the lesser of the base and twice the pickup zone's `fixed_route_fare_cents`
    (a fare-cap multiplier of 2). Finally, a companion charge of 275 cents per companion
    is added, one charge for each of the trip's `num_companions`; the Personal Care
    Attendant is never charged and is not counted in this term."

    Design: Difficulty/combinatorial_formula/trip_fare_nonlinear_cross_zone_cap_binds_then_companions_add
    """
    trip = _cross_zone_two_companions_accepted(api)
    # base=max(500,700)+150=850, cap=min(850, 2*290=580)=580, +275*2=550 -> 1130.
    assert trip["estimated_fare_cents"] == 1130


def test_cross_zone_two_companions_trip_scheduled(api):
    """PRD §3.6: "a successful accept advances the trip from `OFFERED` to `SCHEDULED`."
    PRD §3.8: "The fare is the capped amount plus the companion charge, kept in integer
    cents with no rounding."

    Design: Difficulty/combinatorial_formula/trip_fare_nonlinear_cross_zone_cap_binds_then_companions_add
    """
    trip = _cross_zone_two_companions_accepted(api)
    assert trip["status"] == "SCHEDULED"
    assert trip["estimated_fare_cents"] == 1130


# ==========================================================================
# Corner B — cross-zone, no companion: cap binds at 580
# ==========================================================================
def test_cross_zone_no_companion_cap_binds_at_580(api):
    """PRD §3.8: "otherwise the base equals the greater of the pickup zone's
    `base_fare_cents` and the dropoff zone's `base_fare_cents`, plus a cross-zone
    surcharge of 150 cents. That base is then capped at the ADA ceiling: the capped
    amount is the lesser of the base and twice the pickup zone's `fixed_route_fare_cents`
    (a fare-cap multiplier of 2)."

    Design: Corner/calculations/fare_cross_zone_no_companion_cap_binds_580
    """
    ctx = _rider_two_zones_run(api)
    rider_id = ctx["rider"]["id"]
    za, zb = ctx["zone_a"]["id"], ctx["zone_b"]["id"]
    trip = th.create_offered_trip(api, rider_id, za, zb, dropoff_lat=40.05, dropoff_lng=-74.0)
    resp = th.accept_trip(api, trip["id"], rider_id, ctx["run"]["id"], ctx["run"]["version"])
    validate_success(resp, 200)
    trip = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert trip["estimated_fare_cents"] == 580
