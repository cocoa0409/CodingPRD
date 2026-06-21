"""Trip lifecycle: quote freeze, fare/payout calc, cascades, branching, conservation.

Citations trace to PRD §3.3, §3.4, §3.5, §3.7, §3.8.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_zone, create_rider, create_driver, request_trip, dispatch_tick,
    setup_zone_with_multiplier_2, setup_matched_trip, setup_enroute_trip,
    setup_completed_trip, get_zone, go_online,
    TEST_USERS, make_rider_headers, make_driver_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_trip_final_fare_surge_then_fee_rounding_order(api):
    """PRD §3.7: "The surged amount is the trip's `quoted_base_fare_cents` multiplied by
    its `quoted_multiplier`, rounded half up to a whole number of cents. A flat booking
    fee of 150 cents is then added to that surged amount as an exact integer, and the
    sum is the `final_fare_cents`."
    PRD §3.7: "multiply the base by the surge and round to cents first, then add the
    flat booking fee. The alternative of adding the fee before multiplying is explicitly
    not used."

    base 1000 * 1.50 = 1500; + 150 fee = 1650 (the add-then-multiply reading gives 1725).

    Design: Difficulty/combinatorial_formula/trip_final_fare_surge_then_fee_rounding_order
    """
    # ratio 1.50 -> multiplier 1.50 via demand 3 / supply 2.
    z = create_zone(grid_code="D1", base_fare_cents=1000)
    validate_success(api.create_surge_snapshot(
        z["id"],
        {"observed_demand": 3, "observed_supply": 2, "is_rush_hour": False,
         "effective_from": "2026-06-01T00:00:00Z", "effective_to": "2026-06-01T01:00:00Z",
         "expected_zone_version": z["version"]}, DISPATCHER), 201)
    rider = create_rider(z["id"], wallet_balance_cents=5000)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    trip = request_trip(rider["id"], z["id"], z["id"])
    assert trip["quoted_multiplier"] == pytest.approx(1.50, abs=0.001)
    dispatch_tick(z["id"])
    validate_success(api.start_trip(trip["id"], make_driver_headers(driver["id"])))
    completed = validate_success(api.complete_trip(trip["id"], make_driver_headers(driver["id"])))
    assert completed["final_fare_cents"] == 1650


def test_driver_payout_excludes_booking_fee(api):
    """PRD §3.8: "Take the same surged amount — the `quoted_base_fare_cents` multiplied
    by the `quoted_multiplier`, rounded half up to whole cents — and multiply it by the
    driver share of 0.80, rounding the result half up to whole cents. The payout share
    applies to the surged fare only and excludes the 150-cent booking fee"

    base 1000 * 2.00 = 2000 surged; payout = round(2000 * 0.80) = 1600; fare = 2150.

    Design: Corner/calculations/driver_payout_excludes_booking_fee
    """
    z, rider, driver, trip = setup_enroute_trip(grid_code="M1", multiplier_2=True)
    completed = validate_success(api.complete_trip(trip["id"], make_driver_headers(driver["id"])))
    assert completed["driver_payout_cents"] == 1600
    assert completed["final_fare_cents"] == 2150


def test_trip_freezes_quoted_surge_at_request(api):
    """PRD §3.3: "the trip's `quoted_multiplier` is set to the pickup zone's
    `current_multiplier` as it stands at that moment, and the trip's
    `quoted_base_fare_cents` is set to the pickup zone's `base_fare_cents` at that moment."
    PRD §3.3: "Requesting a trip also increments the pickup zone's `open_demand_count` by 1"

    Design: Corner/entities/trip_freezes_quoted_surge_at_request
    """
    z = setup_zone_with_multiplier_2(grid_code="E1")
    rider = create_rider(z["id"], wallet_balance_cents=5000)
    trip = validate_success(api.create_trip(
        {"rider_id": rider["id"], "pickup_zone_id": z["id"], "dropoff_zone_id": z["id"]},
        make_rider_headers(rider["id"])), 201)
    assert trip["quoted_multiplier"] == pytest.approx(2.00, abs=0.001)
    assert trip["quoted_base_fare_cents"] == 1000
    assert get_zone(z["id"])["open_demand_count"] == 1


def test_new_trip_initial_state_requested(api):
    """PRD §3.3: "Requesting a trip also increments the pickup zone's `open_demand_count`
    by 1, and the new trip starts in `REQUESTED` status."
    PRD §3.3: "The `driver_id` is null while the trip is `REQUESTED` and is set when the
    trip is matched."

    Design: Corner/state_machines/new_trip_initial_state_requested
    """
    z = create_zone(grid_code="H1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=0)
    trip = validate_success(api.create_trip(
        {"rider_id": rider["id"], "pickup_zone_id": z["id"], "dropoff_zone_id": z["id"]},
        make_rider_headers(rider["id"])), 201)
    assert trip["status"] == "REQUESTED"
    assert trip["driver_id"] is None


def test_trip_branching_matched_vs_expired_divergent_side_effects(api):
    """PRD §3.4: "When a match lands, the effects cascade. The trip's `driver_id` is set
    to the selected driver. The selected driver transitions from `AVAILABLE` to
    `ON_TRIP`; as part of that transition the driver's `active_trip_id` is set to the
    matched trip and the driver's current-zone `available_supply_count` is decremented
    by 1, floored at 0. The pickup zone's `open_demand_count` is decremented by 1,
    floored at 0."
    PRD §3.5: "The Dispatcher may expire an unmatched request, moving a trip from
    `REQUESTED` to `EXPIRED`. Expiry is permitted only when the trip is `REQUESTED`, and
    its sole effect is to decrement the pickup zone's `open_demand_count` by 1, floored
    at 0."

    Design: Difficulty/non_linear_state_machine/trip_branching_matched_vs_expired_divergent_side_effects
    """
    z = create_zone(grid_code="E1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=0)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    trip_a = request_trip(rider["id"], z["id"], z["id"])
    trip_b = request_trip(rider["id"], z["id"], z["id"])

    dispatch_tick(z["id"])
    validate_success(api.expire_trip(trip_b["id"], DISPATCHER))

    fa = validate_success(api.get_trip(trip_a["id"], DISPATCHER))
    fb = validate_success(api.get_trip(trip_b["id"], DISPATCHER))
    assert fa["status"] == "MATCHED" and fa["driver_id"] == driver["id"]
    assert fb["status"] == "EXPIRED" and fb["driver_id"] is None
    assert get_zone(z["id"])["open_demand_count"] == 0
    assert validate_success(api.get_driver(driver["id"], DISPATCHER))["status"] == "ON_TRIP"


def test_trip_complete_driver_relocate_supply_cascade_depth3(api):
    """PRD §3.5: "The assigned driver then transitions from `ON_TRIP` back to
    `AVAILABLE`: the driver's `active_trip_id` is cleared, the driver relocates to the
    completed trip's `dropoff_zone_id` (so the driver's `current_zone_id` becomes the
    dropoff zone), and that new current zone's `available_supply_count` is incremented
    by 1."

    Design: Difficulty/transitive_cascade/trip_complete_driver_relocate_supply_cascade_depth3
    """
    zp, rider, driver, trip = setup_enroute_trip(
        grid_code="P1", multiplier_2=False, pickup_dropoff_same=False, dropoff_grid="P2")
    zd_id = trip["dropoff_zone_id"]
    validate_success(api.complete_trip(trip["id"], make_driver_headers(driver["id"])))

    fd = validate_success(api.get_driver(driver["id"], DISPATCHER))
    assert fd["status"] == "AVAILABLE"
    assert fd["current_zone_id"] == zd_id
    assert get_zone(zd_id)["available_supply_count"] == 1
    assert get_zone(zp["id"])["available_supply_count"] == 0


def test_match_then_cancel_conserves_total_available_supply(api):
    """PRD §3.4: "The selected driver transitions from `AVAILABLE` to `ON_TRIP`; as part
    of that transition the driver's `active_trip_id` is set to the matched trip and the
    driver's current-zone `available_supply_count` is decremented by 1, floored at 0."
    PRD §3.5: "Cancelling releases the assigned driver: the driver transitions from
    `ON_TRIP` back to `AVAILABLE`, staying in their current pickup-side zone, and that
    zone's `available_supply_count` is incremented by 1."

    Match decrements supply; cancel restores it, conserving the count at 1.

    Design: Difficulty/compensating_invariant/match_then_cancel_conserves_total_available_supply
    """
    z, rider, driver, trip = setup_matched_trip(grid_code="Q1", wallet_balance_cents=5000)
    validate_success(api.cancel_trip(trip["id"], make_rider_headers(rider["id"])))

    ft = validate_success(api.get_trip(trip["id"], DISPATCHER))
    fd = validate_success(api.get_driver(driver["id"], DISPATCHER))
    assert ft["status"] == "CANCELLED"
    assert fd["status"] == "AVAILABLE"
    assert get_zone(z["id"])["available_supply_count"] == 1


def test_wallet_exactly_equals_fare_completes(api):
    """PRD §3.5: "The fare must be affordable: the rider's `wallet_balance_cents` must be
    at least the computed `final_fare_cents`, and if it is not, completion is rejected
    with `ERR_INSUFFICIENT_WALLET` (HTTP 402). When the fare is affordable, the rider's
    `wallet_balance_cents` is decremented by the `final_fare_cents`."

    Wallet exactly 2150 == final_fare 2150 passes the >= check; wallet ends at 0.

    Design: Difficulty/boundary_precision_check/wallet_exactly_equals_fare_completes
    """
    z, rider, driver, trip = setup_enroute_trip(
        grid_code="K1", multiplier_2=True, wallet_balance_cents=2150)
    completed = validate_success(api.complete_trip(trip["id"], make_driver_headers(driver["id"])))
    assert completed["status"] == "COMPLETED"
    assert completed["final_fare_cents"] == 2150
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 0


def test_insufficient_wallet_on_complete_rejected(api):
    """PRD §3.5: "the rider's `wallet_balance_cents` must be at least the computed
    `final_fare_cents`, and if it is not, completion is rejected with
    `ERR_INSUFFICIENT_WALLET` (HTTP 402)."

    Wallet 2149 < final_fare 2150; trip stays ENROUTE, wallet unchanged.

    Design: Corner/validations/insufficient_wallet_on_complete_rejected
    """
    z, rider, driver, trip = setup_enroute_trip(
        grid_code="O1", multiplier_2=True, wallet_balance_cents=2149)
    resp = api.complete_trip(trip["id"], make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["status"] == "ENROUTE"
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 2149


def test_trip_match_requires_driver_available(api):
    """PRD §3.4: "For a non-airport pickup zone, the candidate set is the drivers whose
    `status` is `AVAILABLE` and whose `current_zone_id` equals the trip's
    `pickup_zone_id`"
    PRD §3.4: "if the candidate set is empty the trip simply stays `REQUESTED` — the tick
    skips it with no error."

    Design: Difficulty/cross_entity_state_dependency/trip_match_requires_driver_available
    """
    z = create_zone(grid_code="L1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=0)
    create_driver(z["id"])  # OFFLINE; never went online
    trip = request_trip(rider["id"], z["id"], z["id"])
    result = validate_success(api.dispatch_tick({"zone_id": z["id"]}, DISPATCHER))
    assert result["matched_count"] == 0
    ft = validate_success(api.get_trip(trip["id"], DISPATCHER))
    assert ft["status"] == "REQUESTED" and ft["driver_id"] is None


def test_complete_already_completed_trip_returns_invalid_state(api):
    """PRD §3.5: "A trip that has reached `COMPLETED`, `CANCELLED`, or `EXPIRED` is
    terminal."
    PRD §2.10: "for transition endpoints, the target resource's current state is checked
    against the state machine, yielding `ERR_INVALID_STATE` when the requested transition
    is not defined from that state."

    A second complete on a COMPLETED trip is rejected and does not re-charge the rider.

    Design: Corner/state_machines/complete_already_completed_trip_returns_invalid_state
    """
    z, rider, driver, trip = setup_completed_trip(grid_code="G1", multiplier_2=True,
                                                  wallet_balance_cents=5000)
    # final_fare 2150; wallet after charge == 2850.
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 2850
    resp = api.complete_trip(trip["id"], make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 2850
