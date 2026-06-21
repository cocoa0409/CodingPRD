"""Disputes (refund calc, branching, conservation) and Quests (earn, expire, windows).

Citations trace to PRD §2.10, §3.5, §3.9, §3.11.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    create_zone, create_rider, create_driver, request_trip, dispatch_tick, go_online,
    setup_completed_trip, create_quest, open_dispute, resolve_dispute,
    TEST_USERS, make_rider_headers, make_driver_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _completed_trip_fare_2150(grid_code, wallet=5000):
    """Helper: a COMPLETED trip at multiplier 2.00, final_fare 2150. Returns (rider, trip)."""
    z, rider, driver, trip = setup_completed_trip(
        grid_code=grid_code, multiplier_2=True, wallet_balance_cents=wallet)
    return rider, trip


def test_dispute_refund_bounded_by_remaining(api):
    """PRD §3.11: "the net paid is the trip's `final_fare_cents` minus the trip's current
    `refunded_cents`, where `refunded_cents` is the sum of prior upheld refunds on the
    same trip applied in `created_at` ascending order; the refund is the smaller of
    `requested_refund_cents` and that net paid."
    PRD §3.11: "A second upheld dispute on a trip whose fare has already been fully
    refunded therefore yields 0, never a second full refund."

    fare 2150, 500 already refunded; second dispute requests 2000 -> bounded to 1650.

    Design: Difficulty/dual_variant_calc/dispute_refund_bounded_by_remaining
    """
    rider, trip = _completed_trip_fare_2150("B1", wallet=5000)
    d1 = open_dispute(rider["id"], trip["id"], reason="OVERCHARGED", requested_refund_cents=500)
    resolve_dispute(d1["id"], "UPHELD")
    d2 = open_dispute(rider["id"], trip["id"], reason="ROUTE_ERROR", requested_refund_cents=2000)
    resolved = validate_success(api.resolve_dispute(d2["id"], {"decision": "UPHELD"}, DISPATCHER))
    assert resolved["refund_cents"] == 1650
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["refunded_cents"] == 2150
    # 5000 - 2150 charge + 500 + 1650 = 5000
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 5000


def test_complete_then_full_refund_conserves_rider_net_cash(api):
    """PRD §3.5: "When the fare is affordable, the rider's `wallet_balance_cents` is
    decremented by the `final_fare_cents`."
    PRD §3.11: "The computed refund is recorded as the dispute's `refund_cents`, added to
    the rider's `wallet_balance_cents`, and added to the disputed trip's `refunded_cents`."

    Full upheld refund (requested 2150) returns the wallet to its pre-trip 5000.

    Design: Difficulty/compensating_invariant/complete_then_full_refund_conserves_rider_net_cash
    """
    rider, trip = _completed_trip_fare_2150("R1", wallet=5000)
    d = open_dispute(rider["id"], trip["id"], reason="OVERCHARGED", requested_refund_cents=2150)
    resolved = validate_success(api.resolve_dispute(d["id"], {"decision": "UPHELD"}, DISPATCHER))
    assert resolved["refund_cents"] == 2150
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["refunded_cents"] == 2150
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 5000


def test_dispute_branching_upheld_vs_rejected_divergent_side_effects(api):
    """PRD §3.11: "The computed refund is recorded as the dispute's `refund_cents`, added
    to the rider's `wallet_balance_cents`, and added to the disputed trip's `refunded_cents`."
    PRD §3.11: "A rejected dispute's `refund_cents` stays 0 and no wallet change occurs."

    Two completed trips, one upheld (refund 500) and one rejected (refund 0).

    Design: Difficulty/non_linear_state_machine/dispute_branching_upheld_vs_rejected_divergent_side_effects
    """
    # Build two completed trips for one rider in one zone (multiplier 2.00, fare 2150 each).
    z, rider, driver, trip_u = setup_completed_trip(grid_code="F1", multiplier_2=True,
                                                    wallet_balance_cents=10000)
    # second trip in same zone, same driver/rider
    trip_r = request_trip(rider["id"], z["id"], z["id"])
    dispatch_tick(z["id"])
    validate_success(api.start_trip(trip_r["id"], make_driver_headers(driver["id"])))
    validate_success(api.complete_trip(trip_r["id"], make_driver_headers(driver["id"])))

    d_u = open_dispute(rider["id"], trip_u["id"], reason="OVERCHARGED", requested_refund_cents=500)
    d_r = open_dispute(rider["id"], trip_r["id"], reason="ROUTE_ERROR", requested_refund_cents=500)
    res_u = validate_success(api.resolve_dispute(d_u["id"], {"decision": "UPHELD"}, DISPATCHER))
    res_r = validate_success(api.resolve_dispute(d_r["id"], {"decision": "REJECTED"}, DISPATCHER))

    assert res_u["status"] == "UPHELD" and res_u["refund_cents"] == 500
    assert res_r["status"] == "REJECTED" and res_r["refund_cents"] == 0
    # 10000 - 2150 - 2150 + 500 = 6200
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 6200


def test_dispute_uphold_requires_trip_completed(api):
    """PRD §3.11: "A dispute may only be opened against a trip whose status is
    `COMPLETED`; an attempt against any other trip status is rejected with
    `ERR_TRIP_NOT_COMPLETED`."

    Opening a dispute on a still-MATCHED trip is rejected before any Dispute exists.

    Design: Difficulty/cross_entity_state_dependency/dispute_uphold_requires_trip_completed
    """
    z = create_zone(grid_code="M1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=5000)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    trip = request_trip(rider["id"], z["id"], z["id"])
    dispatch_tick(z["id"])  # MATCHED, not completed
    resp = api.create_dispute(
        {"trip_id": trip["id"], "reason": "OVERCHARGED", "requested_refund_cents": 500},
        make_rider_headers(rider["id"]))
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_COMPLETED.value)
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["status"] == "MATCHED"


def test_invalid_state_beats_insufficient_wallet_on_complete(api):
    """PRD §2.10: "Then, for transition endpoints, the target resource's current state is
    checked against the state machine, yielding `ERR_INVALID_STATE` when the requested
    transition is not defined from that state. Domain-specific business constraints —
    duplicate grid codes, airport-zone checks, queue eligibility, dispute preconditions,
    wallet sufficiency, window overlaps, the surge OCC check, and request-body field
    validation — follow"

    A MATCHED (not ENROUTE) trip whose rider has wallet 0, completed in one call, returns
    ERR_INVALID_STATE — the state check is ordered before wallet sufficiency.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_insufficient_wallet_on_complete
    """
    z = create_zone(grid_code="H1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=0)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    trip = request_trip(rider["id"], z["id"], z["id"])
    dispatch_tick(z["id"])  # MATCHED (not started)
    resp = api.complete_trip(trip["id"], make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["status"] == "MATCHED"


def test_trip_not_completed_or_invalid_refund_on_matched_dispute(api):
    """PRD §3.11: "A dispute may only be opened against a trip whose status is
    `COMPLETED`; an attempt against any other trip status is rejected with
    `ERR_TRIP_NOT_COMPLETED`. The `requested_refund_cents` must be at least 1, or the
    request is rejected with `ERR_INVALID_REFUND_AMOUNT`."

    Opening a dispute on a MATCHED trip with requested_refund_cents 0 fails both checks;
    PRD does not pin their relative order, so either named error is acceptable.

    Design: Difficulty/priority_pair_validation_conflict/trip_not_completed_beats_invalid_refund_amount_on_dispute
    """
    z = create_zone(grid_code="I1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=5000)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    trip = request_trip(rider["id"], z["id"], z["id"])
    dispatch_tick(z["id"])  # MATCHED
    resp = api.create_dispute(
        {"trip_id": trip["id"], "reason": "OVERCHARGED", "requested_refund_cents": 0},
        make_rider_headers(rider["id"]))
    validate_error_is_one_of(resp, [ApiErrorId.ERR_TRIP_NOT_COMPLETED.value,
                                    ApiErrorId.ERR_INVALID_REFUND_AMOUNT.value])


def test_dispute_invalid_refund_amount_rejected(api):
    """PRD §3.11: "The `requested_refund_cents` must be at least 1, or the request is
    rejected with `ERR_INVALID_REFUND_AMOUNT`."

    A COMPLETED-trip dispute with requested_refund_cents 0 (passing the COMPLETED check
    in isolation) is rejected for the refund amount.

    Design: Corner/validations/dispute_invalid_refund_amount_rejected
    """
    rider, trip = _completed_trip_fare_2150("P1", wallet=5000)
    resp = api.create_dispute(
        {"trip_id": trip["id"], "reason": "OVERCHARGED", "requested_refund_cents": 0},
        make_rider_headers(rider["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REFUND_AMOUNT.value)


def test_quest_earned_on_reaching_target_trips(api):
    """PRD §3.9: "When that increment brings `completed_trips` to at least `target_trips`,
    the quest transitions from `ACTIVE` to `EARNED` and its `paid_out_cents` is set to
    `bonus_cents`."

    A target_trips 1 quest is EARNED after the driver completes one trip.

    Design: Corner/state_machines/quest_earned_on_reaching_target_trips
    """
    z = create_zone(grid_code="I1", base_fare_cents=1000)
    validate_success(api.create_surge_snapshot(
        z["id"], {"observed_demand": 4, "observed_supply": 2, "is_rush_hour": False,
                  "effective_from": "2026-06-01T00:00:00Z",
                  "effective_to": "2026-06-01T01:00:00Z",
                  "expected_zone_version": z["version"]}, DISPATCHER), 201)
    rider = create_rider(z["id"], wallet_balance_cents=5000)
    driver = create_driver(z["id"])
    quest = create_quest(driver["id"], target_trips=1, bonus_cents=5000,
                         window_start="2026-06-01T00:00:00Z", window_end="2026-06-01T23:00:00Z")
    go_online(driver["id"])
    trip = request_trip(rider["id"], z["id"], z["id"])
    dispatch_tick(z["id"])
    validate_success(api.start_trip(trip["id"], make_driver_headers(driver["id"])))
    validate_success(api.complete_trip(trip["id"], make_driver_headers(driver["id"])))

    fq = validate_success(api.get_quest(quest["id"], DISPATCHER))
    assert fq["status"] == "EARNED"
    assert fq["completed_trips"] == 1
    assert fq["paid_out_cents"] == 5000


def test_expire_active_quest_stays_zero_payout(api):
    """PRD §3.9: "The Dispatcher may instead expire a quest still in `ACTIVE`, moving it
    to `EXPIRED`; an expired quest's `paid_out_cents` stays 0."

    Design: Corner/state_machines/expire_active_quest_stays_zero_payout
    """
    z = create_zone(grid_code="J1", base_fare_cents=1000)
    driver = create_driver(z["id"])
    quest = create_quest(driver["id"], target_trips=3, bonus_cents=5000,
                         window_start="2026-06-01T00:00:00Z", window_end="2026-06-01T05:00:00Z")
    expired = validate_success(api.expire_quest(quest["id"], DISPATCHER))
    assert expired["status"] == "EXPIRED"
    assert expired["paid_out_cents"] == 0


def test_quest_window_overlap_closed_adjacency_forbidden(api):
    """PRD §3.9: "A new quest is rejected with `ERR_QUEST_WINDOW_OVERLAP` if its interval
    overlaps or merely touches the interval of any existing `ACTIVE` or `EARNED` quest
    for the same `driver_id`"
    PRD §3.9: "Boundary contact, where the new window's `window_start` equals an existing
    window's `window_end`, does conflict here."

    Second quest window_start 12:00 == first window_end 12:00 is rejected.

    Design: Difficulty/resource_temporal_overlap/quest_window_overlap_closed_adjacency_forbidden
    """
    z = create_zone(grid_code="O1", base_fare_cents=1000)
    driver = create_driver(z["id"])
    create_quest(driver["id"], target_trips=3, bonus_cents=5000,
                 window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T12:00:00Z")
    resp = api.create_quest(
        {"driver_id": driver["id"], "target_trips": 2, "bonus_cents": 3000,
         "window_start": "2026-06-01T12:00:00Z", "window_end": "2026-06-01T14:00:00Z"},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_QUEST_WINDOW_OVERLAP.value)
