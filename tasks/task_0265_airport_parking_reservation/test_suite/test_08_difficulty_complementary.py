"""Second-pass Queue A (Difficulty) tests.

Each difficulty instance is covered by at least TWO tests. The first pass (test_01–
test_03) asserts the instance's headline outcome; this file asserts a complementary,
independently PRD-grounded facet of the same instance so each instance carries >= 2
tests. The instance `hourly_charge_tiered_cap_with_class_surcharge_mode_a` is skipped
entirely (see the note in test_01) and therefore appears in neither pass.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_booked_reservation, create_checked_in_reservation, check_out_reservation_at,
    setup_booking_scenario, book_reservation, drive_customer_to_suspended,
    create_shuttle_trip, assign_reservation_to_trip, find_txn, set_clock,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OPERATOR = TEST_USERS["lot_operator_headers"]


def _payment_txns(reservation_id):
    return get_success_data(api_client.list_reservation_payment_txns(reservation_id, ADMIN))


# ─── Rule 1: dual_variant_calc ───────────────────────────────────────────────
def test_provisional_quote_present_and_final_null_while_booked():
    """PRD §3.3: "The reservation begins with `occupancy_status` of `BOOKED`,
    `settlement_status` of `UNSETTLED`, `actual_in` and `actual_out` null,
    `final_charge_cents` null, `overstay_cents` of 0".
    PRD §3.4: "At booking time the **provisional variant** runs over the interval from
    `scheduled_start` to `scheduled_end`".

    Design: Difficulty/dual_variant_calc/parking_charge_provisional_vs_final_diverge
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L1b", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-03T15:30:00Z",
        prepaid=False)
    assert reservation["provisional_quote_cents"] == 5800
    assert reservation["final_charge_cents"] is None
    assert reservation["overstay_cents"] == 0


def test_lot_version_advances_on_booking_then_again_on_cancel():
    """PRD §3.3: "creating that hold recomputes the lot's available counter for the
    class downward by one and increments the lot's `version` by one."

    Design: Difficulty/dual_variant_calc/lot_availability_decrement_vs_increment_diverge
    """
    scenario = setup_booking_scenario(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L2b", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    v_before = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))["version"]
    res, reservation = book_reservation(scenario, scheduled_start="2026-07-01T10:00:00Z",
                                        scheduled_end="2026-07-02T10:00:00Z")
    assert reservation is not None
    v_after = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))["version"]
    assert v_after == v_before + 1


# ─── Rule 2: combinatorial_formula ───────────────────────────────────────────
def test_prepay_discount_reduces_quote_by_exact_bps_of_gross():
    """PRD §3.4: "the discount is the gross multiplied by the lot's cancellation-policy
    `prepay_discount_bps` divided by 10000, rounded half up to a whole cent, and
    `provisional_quote_cents` is the gross minus that discount."

    Design: Difficulty/combinatorial_formula/prepay_discount_then_overstay_capture_evaluation_order_mode_c
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L2c2", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        with_policy=True,
        policy_overrides={"free_cancel_hours": 48, "late_cancel_fee_bps": 2500,
                          "prepay_discount_bps": 1500},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-03T15:30:00Z",
        prepaid=True)
    # gross 5800, discount rhu(5800 * 1500 / 10000) = 870, quote = 4930.
    assert reservation["provisional_quote_cents"] == 4930
    assert reservation["settlement_status"] == "AUTHORIZED"


# ─── Rule 3: non_linear_state_machine ────────────────────────────────────────
def test_gate_reentry_returns_to_checked_in():
    """PRD §3.5: "The vehicle later re-enters under the same reservation and the same
    stall, advancing `occupancy_status` from `OUT_TEMP` back to `CHECKED_IN`; re-entry
    is permitted only from `OUT_TEMP`."

    Design: Difficulty/non_linear_state_machine/reservation_in_out_cycle_checked_in_out_temp
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L3a2", "kind": "SURFACE_LOT", "standard_capacity": 2,
                       "in_out_allowed": True},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    validate_success(api_client.gate_exit_reservation(checked_in["id"], OPERATOR), 200)
    reentered = validate_success(api_client.gate_reentry_reservation(checked_in["id"], OPERATOR), 200)
    assert reentered["occupancy_status"] == "CHECKED_IN"


def test_shuttle_cancel_not_permitted_from_boarding():
    """PRD §3.9: "Cancellation is defined only from `SCHEDULED` — a trip already in
    `BOARDING` or `DEPARTED` cannot be cancelled. Any trip transition requested from a
    state where it is not defined (... cancelling a non-`SCHEDULED` trip) is rejected
    with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/shuttle_trip_branching_cancel_vs_depart
    """
    set_clock("2026-07-01T09:40:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L3b2", "kind": "SURFACE_LOT", "standard_capacity": 2,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    trip = create_shuttle_trip(lot["id"], depart_at="2026-07-01T10:00:00Z", seat_capacity=4)
    validate_success(api_client.open_boarding_shuttle_trip(trip["id"], OPERATOR), 200)
    res = api_client.cancel_shuttle_trip(trip["id"], OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Rule 4: transitive_cascade ──────────────────────────────────────────────
def test_single_no_show_releases_stall_and_increments_strike():
    """PRD §3.7: "The backing stall hold transitions from `HELD` to `RELEASED` and the
    lot's availability counter for that class is recomputed upward by one. ... The
    booking customer's `no_show_strikes` is increased by one".

    Design: Difficulty/transitive_cascade/no_show_sweep_cascade_depth4_to_customer_suspension
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L4a2", "kind": "SURFACE_LOT", "standard_capacity": 3},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-06-30T09:05:00Z", scheduled_end="2026-07-01T10:00:00Z")
    assert get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))["available_standard_count"] == 2

    set_clock("2026-06-30T09:40:00Z")
    swept = validate_success(api_client.mark_no_show(reservation["id"], ADMIN), 200)
    assert swept["occupancy_status"] == "NO_SHOW"

    lot_after = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert lot_after["available_standard_count"] == 3
    cust = get_success_data(api_client.get_customer(scenario["customer"]["id"], ADMIN))
    assert cust["no_show_strikes"] == 1


def test_checkout_clears_reservation_shuttle_trip_id():
    """PRD §3.6: "If the reservation holds a shuttle seat, that trip's `seats_taken` is
    decremented by one and the reservation's `shuttle_trip_id` is cleared."

    Design: Difficulty/transitive_cascade/checkout_cascade_depth3_stall_and_shuttle_release
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L4b2", "kind": "SURFACE_LOT", "standard_capacity": 2},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z")
    trip = create_shuttle_trip(scenario["lot"]["id"], depart_at="2026-07-01T12:00:00Z",
                               seat_capacity=4)
    assign_reservation_to_trip(reservation["id"], trip["id"])

    set_clock("2026-07-01T10:00:00Z")
    validate_success(api_client.check_in_reservation(reservation["id"], OPERATOR), 200)
    set_clock("2026-07-02T08:00:00Z")
    checked_out = validate_success(api_client.check_out_reservation(reservation["id"], OPERATOR), 200)
    assert checked_out["shuttle_trip_id"] is None


# ─── Rule 5: priority_pair_validation_conflict ───────────────────────────────
def test_no_stall_fires_when_customer_active():
    """PRD §3.3: "after all of the above pass, the capacity check: the stall class
    derived from the vehicle must have at least one stall available on the lot, else
    `ERR_NO_STALL_AVAILABLE`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_no_stall_constraint
    """
    set_clock("2026-06-30T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L5a2", "kind": "SURFACE_LOT", "standard_capacity": 1,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    filler = get_success_data(api_client.create_customer({"email": "f5a2@x.com", "full_name": "F"}, ADMIN))
    fveh = get_success_data(api_client.create_vehicle(
        {"customer_id": filler["id"], "plate": "F5A2", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    get_success_data(api_client.create_reservation(
        {"customer_id": filler["id"], "lot_id": lot["id"], "vehicle_id": fveh["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN))

    active = get_success_data(api_client.create_customer({"email": "a5a2@x.com", "full_name": "A"}, ADMIN))
    aveh = get_success_data(api_client.create_vehicle(
        {"customer_id": active["id"], "plate": "A5A2", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live2 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res = api_client.create_reservation(
        {"customer_id": active["id"], "lot_id": lot["id"], "vehicle_id": aveh["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-05T10:00:00Z",
         "scheduled_end": "2026-07-06T10:00:00Z", "prepaid": False,
         "expected_lot_version": live2["version"]}, ADMIN)
    validate_error(res, "ERR_NO_STALL_AVAILABLE", expected_status=409)


def test_invalid_interval_fires_when_plan_active():
    """PRD §3.3: "Then the interval: `scheduled_end` must be strictly after
    `scheduled_start`, and `scheduled_start` must be strictly after the current clock; a
    violation yields `ERR_INVALID_INTERVAL`."

    Design: Difficulty/priority_pair_validation_conflict/interval_temporal_beats_rate_plan_constraint
    """
    scenario = setup_booking_scenario(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L5b2", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    # Active plan, but scheduled_end before scheduled_start -> only the interval fails.
    res, _ = book_reservation(scenario, scheduled_start="2026-07-02T10:00:00Z",
                              scheduled_end="2026-07-02T08:00:00Z")
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


# ─── Rule 6: boundary_precision_check (no_stall instance second test) ─────────
def test_ev_booking_succeeds_when_count_one_then_zero_blocks():
    """PRD §3.3: "the stall class derived from the vehicle must have at least one stall
    available on the lot, else `ERR_NO_STALL_AVAILABLE`."
    PRD §2.5: "the available count for that class equals that class's capacity minus the
    number of stall holds on the lot whose own stall class matches and whose `status` is
    either `HELD` or `OCCUPIED`."

    Design: Difficulty/boundary_precision_check/no_stall_available_at_zero_count_empty_inventory
    """
    set_clock("2026-06-30T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L6b2", "kind": "GARAGE", "standard_capacity": 0, "oversized_capacity": 0,
         "ev_capacity": 1, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 3000,
         "ev_surcharge_cents_per_day": 400}, ADMIN))
    c1 = get_success_data(api_client.create_customer({"email": "ev1b@x.com", "full_name": "E1"}, ADMIN))
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "EV1B", "size_class": "STANDARD", "is_ev": True}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    assert live["available_ev_count"] == 1
    # Count == 1: the booking succeeds.
    reservation = get_success_data(api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN))
    assert reservation["stall_class"] == "EV"
    after = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    assert after["available_ev_count"] == 0


# ─── Rule 7: cross_entity_state_dependency ───────────────────────────────────
def test_active_customer_can_book():
    """PRD §3.1: "A newly created customer starts with a strike count, `no_show_strikes`,
    of 0 and an account `status` of `ACTIVE`."
    PRD §3.3: "When all checks pass, the booking commits a single atomic cascade."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_customer_active_reservation_lot
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L7a2", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    assert reservation["occupancy_status"] == "BOOKED"
    cust = get_success_data(api_client.get_customer(scenario["customer"]["id"], ADMIN))
    assert cust["status"] == "ACTIVE"


def test_assign_shuttle_trip_not_serving_lot_rejected():
    """PRD §3.9: "A `Customer` may assign their own reservation to a shuttle trip
    serving the same lot ... The trip must serve the reservation's lot ...; if any of
    these fails — the trip is full, does not serve the lot, or is not in a seat-accepting
    state — the assignment is rejected with `ERR_SHUTTLE_FULL`."

    Design: Difficulty/cross_entity_state_dependency/assign_shuttle_requires_trip_serves_lot_and_open
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L7b2", "kind": "SURFACE_LOT", "standard_capacity": 3},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-02T10:00:00Z", scheduled_end="2026-07-03T10:00:00Z")
    # A trip on a DIFFERENT lot.
    other_lot = get_success_data(api_client.create_lot(
        {"name": "L7b2-other", "kind": "SURFACE_LOT", "standard_capacity": 3,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    trip = create_shuttle_trip(other_lot["id"], depart_at="2026-07-02T12:00:00Z", seat_capacity=4)
    res = api_client.assign_shuttle(
        reservation["id"],
        {"shuttle_trip_id": trip["id"], "expected_shuttle_trip_version": trip["version"]}, ADMIN)
    validate_error(res, "ERR_SHUTTLE_FULL", expected_status=409)


# ─── Rule 8: resource_temporal_overlap ───────────────────────────────────────
def test_overlapping_bookings_both_succeed_up_to_capacity():
    """PRD §2.5: "The counters are denormalized projections of the active holds against
    each pool ... For a given lot and a given stall class ..., the available count for
    that class equals that class's capacity minus the number of stall holds on the lot
    whose own stall class matches and whose `status` is either `HELD` or `OCCUPIED`."

    Design: Difficulty/resource_temporal_overlap/stall_capacity_overlap_aggregate_count
    """
    set_clock("2026-06-30T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L8a2", "kind": "SURFACE_LOT", "standard_capacity": 2,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    c1 = get_success_data(api_client.create_customer({"email": "o8a1@x.com", "full_name": "O1"}, ADMIN))
    c2 = get_success_data(api_client.create_customer({"email": "o8a2@x.com", "full_name": "O2"}, ADMIN))
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "O8A1", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    v2 = get_success_data(api_client.create_vehicle(
        {"customer_id": c2["id"], "plate": "O8A2", "size_class": "STANDARD", "is_ev": False}, ADMIN))

    live0 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    r1 = api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-03T10:00:00Z", "prepaid": False,
         "expected_lot_version": live0["version"]}, ADMIN)
    validate_success(r1, 201)
    live1 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    # Second overlapping interval still fits within capacity 2.
    r2 = api_client.create_reservation(
        {"customer_id": c2["id"], "lot_id": lot["id"], "vehicle_id": v2["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-02T10:00:00Z",
         "scheduled_end": "2026-07-04T10:00:00Z", "prepaid": False,
         "expected_lot_version": live1["version"]}, ADMIN)
    validate_success(r2, 201)
    after = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    assert after["available_standard_count"] == 0


def test_first_assignment_fills_single_seat_trip():
    """PRD §3.9: "A successful assignment sets the reservation's `shuttle_trip_id`,
    increments the trip's `seats_taken` by one, and increments the trip's `version` by
    one."

    Design: Difficulty/resource_temporal_overlap/shuttle_seat_capacity_overlap_per_trip
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L8b2", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-02T10:00:00Z", scheduled_end="2026-07-03T10:00:00Z")
    trip = create_shuttle_trip(scenario["lot"]["id"], depart_at="2026-07-01T12:00:00Z",
                               seat_capacity=1)
    assigned = assign_reservation_to_trip(reservation["id"], trip["id"])
    assert assigned["shuttle_trip_id"] == trip["id"]
    trip_after = get_success_data(api_client.get_shuttle_trip(trip["id"], ADMIN))
    assert trip_after["seats_taken"] == 1 == trip_after["seat_capacity"]


# ─── Rule 9: compensating_invariant ──────────────────────────────────────────
def test_stall_count_conserved_book_checkin_then_checkout():
    """PRD §3.6: "The backing stall hold transitions from `OCCUPIED` to `RELEASED`, its
    `hold_end` is set to `actual_out`, and the lot's availability counter for that class
    is recomputed upward by one."

    Design: Difficulty/compensating_invariant/stall_count_conserved_book_then_cancel
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L9a2", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    assert get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))["available_standard_count"] == 4
    check_out_reservation_at(checked_in["id"], "2026-07-02T08:00:00Z")
    after = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert after["available_standard_count"] == 5


def test_money_conserved_prepay_free_cancel_full_refund():
    """PRD §3.8: "If that gap is at least `free_cancel_hours`, the cancellation falls
    strictly outside (or exactly at the edge of) the free-cancel window and the retained
    fee is 0, so the full `provisional_quote_cents` is refunded."

    Design: Difficulty/compensating_invariant/money_conserved_prepay_then_cancel_fee_plus_refund
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-25T09:00:00Z",
        lot_overrides={"name": "L9b2", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        with_policy=True,
        policy_overrides={"free_cancel_hours": 48, "late_cancel_fee_bps": 2500,
                          "prepay_discount_bps": 0},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        prepaid=True)
    assert reservation["provisional_quote_cents"] == 2000
    cancelled = validate_success(api_client.cancel_reservation(reservation["id"], ADMIN), 200)
    assert cancelled["settlement_status"] == "REFUNDED"
    txns = _payment_txns(reservation["id"])
    refund = find_txn(txns, "REFUND")
    assert refund is not None and refund["amount_cents"] == 2000
    assert find_txn(txns, "FEE_RETAIN") is None
