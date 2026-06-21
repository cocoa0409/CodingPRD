"""Second tests for each difficulty-design instance: boundary neighbours, alternate
variants, and additional side-effect assertions distinct from the first test.

Citations trace to PRD §2.1, §2.9, §3.4, §3.5, §3.6, §3.7, §3.9, §3.11.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    create_zone, create_rider, create_driver, request_trip, dispatch_tick, go_online,
    create_surge_snapshot_payload, create_quest, open_dispute, resolve_dispute,
    setup_matched_trip, setup_enroute_trip, setup_completed_trip, get_zone,
    setup_airport_zone, join_queue,
    TEST_USERS, make_rider_headers, make_driver_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ── dual_variant_calc ──

def test_surge_standard_window_no_rush_step_added(api):
    """PRD §3.6: "Third, if `is_rush_hour` is true, add a rush-hour step of 0.50 to the
    banded raw multiplier — the step is added to the banded value, never to the ratio."

    With is_rush_hour false the banded raw (1.50 from ratio 1.50) is used unchanged; no
    rush step is added.

    Design: Difficulty/dual_variant_calc/surge_multiplier_rush_vs_standard_window
    """
    z = create_zone(grid_code="A1", base_fare_cents=1000)
    snap = validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=3, observed_supply=2, expected_zone_version=z["version"],
            is_rush_hour=False), DISPATCHER), 201)
    assert snap["multiplier"] == pytest.approx(1.50, abs=0.001)


def test_dispute_refund_full_when_within_remaining(api):
    """PRD §3.11: "the refund is the smaller of `requested_refund_cents` and that net
    paid."

    With nothing previously refunded on a 2150 fare, a 500 request refunds the full 500
    (it is below the remaining net paid).

    Design: Difficulty/dual_variant_calc/dispute_refund_bounded_by_remaining
    """
    z, rider, driver, trip = setup_completed_trip(grid_code="B1", multiplier_2=True,
                                                  wallet_balance_cents=5000)
    d = open_dispute(rider["id"], trip["id"], reason="OVERCHARGED", requested_refund_cents=500)
    resolved = validate_success(api.resolve_dispute(d["id"], {"decision": "UPHELD"}, DISPATCHER))
    assert resolved["refund_cents"] == 500
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["refunded_cents"] == 500


# ── combinatorial_formula ──

def test_trip_final_fare_at_cap_multiplier(api):
    """PRD §3.7: "The surged amount is the trip's `quoted_base_fare_cents` multiplied by
    its `quoted_multiplier`, rounded half up to a whole number of cents. A flat booking
    fee of 150 cents is then added to that surged amount as an exact integer, and the
    sum is the `final_fare_cents`."

    base 1000 * 2.00 = 2000; + 150 = 2150.

    Design: Difficulty/combinatorial_formula/trip_final_fare_surge_then_fee_rounding_order
    """
    z, rider, driver, trip = setup_enroute_trip(grid_code="D1", multiplier_2=True,
                                                wallet_balance_cents=5000)
    assert trip["quoted_multiplier"] == pytest.approx(2.00, abs=0.001)
    completed = validate_success(api.complete_trip(trip["id"], make_driver_headers(driver["id"])))
    assert completed["final_fare_cents"] == 2150


# ── non_linear_state_machine ──

def test_match_branch_clears_demand_and_assigns_driver(api):
    """PRD §3.4: "The trip's `driver_id` is set to the selected driver. The selected
    driver transitions from `AVAILABLE` to `ON_TRIP`; as part of that transition the
    driver's `active_trip_id` is set to the matched trip and the driver's current-zone
    `available_supply_count` is decremented by 1, floored at 0. The pickup zone's
    `open_demand_count` is decremented by 1, floored at 0."

    Asserts the MATCH branch's supply/demand counter side effects.

    Design: Difficulty/non_linear_state_machine/trip_branching_matched_vs_expired_divergent_side_effects
    """
    z, rider, driver, trip = setup_matched_trip(grid_code="E1", wallet_balance_cents=0)
    assert trip["status"] == "MATCHED" and trip["driver_id"] == driver["id"]
    fz = get_zone(z["id"])
    assert fz["open_demand_count"] == 0
    assert fz["available_supply_count"] == 0
    fd = validate_success(api.get_driver(driver["id"], DISPATCHER))
    assert fd["active_trip_id"] == trip["id"]


def test_dispute_reject_branch_leaves_wallet_untouched(api):
    """PRD §3.11: "When the decision rejects the dispute, it moves from `OPEN` to
    `REJECTED`; this requires only that the dispute be `OPEN`. A rejected dispute's
    `refund_cents` stays 0 and no wallet change occurs."

    Asserts the REJECT branch in isolation: refund 0, wallet unchanged from post-charge.

    Design: Difficulty/non_linear_state_machine/dispute_branching_upheld_vs_rejected_divergent_side_effects
    """
    z, rider, driver, trip = setup_completed_trip(grid_code="G1", multiplier_2=True,
                                                  wallet_balance_cents=5000)
    # post-charge wallet == 2850
    d = open_dispute(rider["id"], trip["id"], reason="ROUTE_ERROR", requested_refund_cents=500)
    resolved = validate_success(api.resolve_dispute(d["id"], {"decision": "REJECTED"}, DISPATCHER))
    assert resolved["status"] == "REJECTED" and resolved["refund_cents"] == 0
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 2850
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["refunded_cents"] == 0


# ── transitive_cascade ──

def test_complete_clears_active_trip_and_relocates(api):
    """PRD §3.5: "the driver's `active_trip_id` is cleared, the driver relocates to the
    completed trip's `dropoff_zone_id` (so the driver's `current_zone_id` becomes the
    dropoff zone), and that new current zone's `available_supply_count` is incremented
    by 1."

    Asserts active_trip_id is cleared on completion (the first cascade hop), distinct
    from the supply-count assertion in the primary test.

    Design: Difficulty/transitive_cascade/trip_complete_driver_relocate_supply_cascade_depth3
    """
    zp, rider, driver, trip = setup_enroute_trip(
        grid_code="P1", pickup_dropoff_same=False, dropoff_grid="P2", wallet_balance_cents=5000)
    validate_success(api.complete_trip(trip["id"], make_driver_headers(driver["id"])))
    fd = validate_success(api.get_driver(driver["id"], DISPATCHER))
    assert fd["active_trip_id"] is None
    assert fd["current_zone_id"] == trip["dropoff_zone_id"]


def test_withdraw_resequences_remaining_entry(api):
    """PRD §3.10: "Whether an entry leaves the queue by withdrawal or by being
    `DISPATCHED` during matching, the remaining `WAITING` entries in the same airport
    zone re-sequence their `position` by `joined_at` ascending with `created_at`
    ascending as a tie-break."

    An explicit withdraw (not go-offline) of the head entry re-sequences the next to 1.

    Design: Difficulty/transitive_cascade/go_offline_queue_withdraw_resequence_depth2
    """
    az = setup_airport_zone(grid_code="Z8", base_fare_cents=1500)
    d1 = create_driver(az["id"], name="D1")
    d2 = create_driver(az["id"], name="D2")
    go_online(d1["id"])
    go_online(d2["id"])
    q1 = join_queue(az["id"], d1["id"])
    q2 = join_queue(az["id"], d2["id"])
    validate_success(api.withdraw_airport_queue_entry(q1["id"], make_driver_headers(d1["id"])))
    fq2 = validate_success(api.get_airport_queue_entry(q2["id"], DISPATCHER))
    assert fq2["status"] == "WAITING" and fq2["position"] == 1


# ── priority_pair_validation_conflict ──

def test_invalid_state_on_complete_does_not_charge_wallet(api):
    """PRD §2.10: "for transition endpoints, the target resource's current state is
    checked against the state machine, yielding `ERR_INVALID_STATE` when the requested
    transition is not defined from that state. Domain-specific business constraints — ...
    wallet sufficiency, ... — follow"
    PRD §3.5: "No fare is charged on cancellation and the trip's `final_fare_cents` stays 0."

    A MATCHED trip with a zero wallet returns ERR_INVALID_STATE and the rider's wallet is
    not touched (the wallet check never runs).

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_insufficient_wallet_on_complete
    """
    z, rider, driver, trip = setup_matched_trip(grid_code="H1", wallet_balance_cents=0)
    resp = api.complete_trip(trip["id"], make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 0


def test_dispute_on_expired_trip_rejected_not_completed(api):
    """PRD §3.11: "A dispute may only be opened against a trip whose status is
    `COMPLETED`; an attempt against any other trip status is rejected with
    `ERR_TRIP_NOT_COMPLETED`."

    A dispute against an EXPIRED trip with a valid positive refund amount isolates the
    COMPLETED precondition: ERR_TRIP_NOT_COMPLETED fires.

    Design: Difficulty/priority_pair_validation_conflict/trip_not_completed_beats_invalid_refund_amount_on_dispute
    """
    z = create_zone(grid_code="I1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=5000)
    trip = request_trip(rider["id"], z["id"], z["id"])
    validate_success(api.expire_trip(trip["id"], DISPATCHER))  # EXPIRED
    resp = api.create_dispute(
        {"trip_id": trip["id"], "reason": "OVERCHARGED", "requested_refund_cents": 100},
        make_rider_headers(rider["id"]))
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_COMPLETED.value)


# ── boundary_precision_check ──

def test_surge_ratio_just_below_two_bands_lower(api):
    """PRD §3.6: "a ratio of at least 1.00 but below 2.00 gives 1.50; a ratio of at least
    2.00 but below 3.00 gives 2.00"

    Ratio 1.50 (demand 3 / supply 2) is below 2.00 and bands to 1.50, the neighbour just
    below the 2.00 inclusive boundary tested in the primary case.

    Design: Difficulty/boundary_precision_check/surge_ratio_band_boundary_exactly_two
    """
    z = create_zone(grid_code="J1", base_fare_cents=1000)
    snap = validate_success(api.create_surge_snapshot(
        z["id"], create_surge_snapshot_payload(
            observed_demand=3, observed_supply=2, expected_zone_version=z["version"]),
        DISPATCHER), 201)
    assert snap["ratio"] == pytest.approx(1.50, abs=0.001)
    assert snap["multiplier"] == pytest.approx(1.50, abs=0.001)


def test_wallet_one_below_fare_rejected(api):
    """PRD §3.5: "the rider's `wallet_balance_cents` must be at least the computed
    `final_fare_cents`, and if it is not, completion is rejected with
    `ERR_INSUFFICIENT_WALLET` (HTTP 402)."

    Wallet 2149 (one cent below fare 2150) fails the >= check — the X-1 neighbour of the
    exact-equality boundary.

    Design: Difficulty/boundary_precision_check/wallet_exactly_equals_fare_completes
    """
    z, rider, driver, trip = setup_enroute_trip(grid_code="K1", multiplier_2=True,
                                                wallet_balance_cents=2149)
    resp = api.complete_trip(trip["id"], make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_WALLET.value)
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["status"] == "ENROUTE"


# ── cross_entity_state_dependency ──

def test_available_driver_enables_match(api):
    """PRD §3.4: "For a non-airport pickup zone, the candidate set is the drivers whose
    `status` is `AVAILABLE` and whose `current_zone_id` equals the trip's
    `pickup_zone_id`, ranked by `created_at` ascending so that the earliest-registered
    driver is chosen first."

    The positive counterpart: with the driver AVAILABLE the trip matches (matched_count 1).

    Design: Difficulty/cross_entity_state_dependency/trip_match_requires_driver_available
    """
    z = create_zone(grid_code="L1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=0)
    driver = create_driver(z["id"])
    go_online(driver["id"])
    trip = request_trip(rider["id"], z["id"], z["id"])
    result = validate_success(api.dispatch_tick({"zone_id": z["id"]}, DISPATCHER))
    assert result["matched_count"] == 1
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["status"] == "MATCHED"


def test_dispute_allowed_on_completed_trip(api):
    """PRD §3.11: "After a trip completes, the `Rider` who took it may open a `Dispute`."
    PRD §3.11: "On creation the dispute's `rider_id` is copied from the disputed trip's
    `rider_id`, its `status` starts at `OPEN`"

    The positive counterpart: a dispute on a COMPLETED trip is accepted and opens OPEN.

    Design: Difficulty/cross_entity_state_dependency/dispute_uphold_requires_trip_completed
    """
    z, rider, driver, trip = setup_completed_trip(grid_code="M1", multiplier_2=True,
                                                  wallet_balance_cents=5000)
    d = validate_success(api.create_dispute(
        {"trip_id": trip["id"], "reason": "OVERCHARGED", "requested_refund_cents": 500},
        make_rider_headers(rider["id"])), 201)
    assert d["status"] == "OPEN"
    assert d["rider_id"] == rider["id"]


# ── resource_temporal_overlap ──

def test_quest_window_overlapping_interval_rejected(api):
    """PRD §3.9: "A new quest is rejected with `ERR_QUEST_WINDOW_OVERLAP` if its interval
    overlaps or merely touches the interval of any existing `ACTIVE` or `EARNED` quest
    for the same `driver_id` — that is, if the new window's `window_start` is at or
    before the existing window's `window_end` and the existing window's `window_start` is
    at or before the new window's `window_end`."

    A second quest [11:00, 13:00] strictly overlapping the first [10:00, 12:00] is rejected.

    Design: Difficulty/resource_temporal_overlap/quest_window_overlap_closed_adjacency_forbidden
    """
    z = create_zone(grid_code="O1", base_fare_cents=1000)
    driver = create_driver(z["id"])
    create_quest(driver["id"], target_trips=3, bonus_cents=5000,
                 window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T12:00:00Z")
    resp = api.create_quest(
        {"driver_id": driver["id"], "target_trips": 2, "bonus_cents": 3000,
         "window_start": "2026-06-01T11:00:00Z", "window_end": "2026-06-01T13:00:00Z"},
        DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_QUEST_WINDOW_OVERLAP.value)


# ── compensating_invariant ──

def test_match_then_cancel_releases_driver_to_available(api):
    """PRD §3.5: "Cancelling releases the assigned driver: the driver transitions from
    `ON_TRIP` back to `AVAILABLE`, staying in their current pickup-side zone, and that
    zone's `available_supply_count` is incremented by 1. No fare is charged on
    cancellation and the trip's `final_fare_cents` stays 0."

    Asserts the cancel branch's no-charge invariant alongside supply restoration.

    Design: Difficulty/compensating_invariant/match_then_cancel_conserves_total_available_supply
    """
    z, rider, driver, trip = setup_matched_trip(grid_code="Q1", wallet_balance_cents=5000)
    cancelled = validate_success(api.cancel_trip(trip["id"], make_rider_headers(rider["id"])))
    assert cancelled["final_fare_cents"] == 0
    assert validate_success(api.get_driver(driver["id"], DISPATCHER))["status"] == "AVAILABLE"
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 5000


def test_partial_refund_leaves_net_paid_positive(api):
    """PRD §3.11: "the net paid is the trip's `final_fare_cents` minus the trip's current
    `refunded_cents` ... The computed refund is recorded as the dispute's `refund_cents`,
    added to the rider's `wallet_balance_cents`, and added to the disputed trip's
    `refunded_cents`."

    A partial upheld refund (500 of a 2150 fare) credits exactly 500 and the trip's
    refunded_cents becomes 500, conserving cash flow per the ledger identity.

    Design: Difficulty/compensating_invariant/complete_then_full_refund_conserves_rider_net_cash
    """
    z, rider, driver, trip = setup_completed_trip(grid_code="R1", multiplier_2=True,
                                                  wallet_balance_cents=5000)
    d = open_dispute(rider["id"], trip["id"], reason="OVERCHARGED", requested_refund_cents=500)
    resolved = validate_success(api.resolve_dispute(d["id"], {"decision": "UPHELD"}, DISPATCHER))
    assert resolved["refund_cents"] == 500
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["refunded_cents"] == 500
    # 5000 - 2150 + 500 = 3350
    assert validate_success(api.get_rider(rider["id"], DISPATCHER))["wallet_balance_cents"] == 3350


# ── corner: RBAC ownership (not yet covered) ──

def test_driver_cannot_complete_other_drivers_trip(api):
    """PRD §2.1: "a driver's `id` must equal the trip's `driver_id` when starting or
    completing a trip ... A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/driver_cannot_complete_other_drivers_trip
    """
    z, rider, d1, trip = setup_enroute_trip(grid_code="W1", multiplier_2=True,
                                            wallet_balance_cents=5000)
    d2 = create_driver(z["id"], name="D2")
    resp = api.complete_trip(trip["id"], make_driver_headers(d2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert validate_success(api.get_trip(trip["id"], DISPATCHER))["status"] == "ENROUTE"
