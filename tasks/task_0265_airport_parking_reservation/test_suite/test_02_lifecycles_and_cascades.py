"""Non-linear lifecycles and transitive cascades: the in/out occupancy cycle, the
shuttle branching machine, the no-show cascade to customer suspension, the check-out
cascade releasing stall + shuttle seat, and stall-count conservation on book+cancel.

Queue A (Difficulty) instances for non_linear_state_machine, transitive_cascade, and
the stall slice of compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_booked_reservation, create_checked_in_reservation,
    create_shuttle_trip, assign_reservation_to_trip, set_clock,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OPERATOR = TEST_USERS["lot_operator_headers"]


# ─── Rule 3: non_linear_state_machine ────────────────────────────────────────
def test_in_out_cycle_keeps_stall_held_throughout():
    """PRD §3.5: "a checked-in vehicle may make a temporary exit, advancing
    `occupancy_status` from `CHECKED_IN` to `OUT_TEMP`. A temporary exit retains the
    stall — the backing hold stays `OCCUPIED` throughout the in/out trip".
    PRD §3.5: "The vehicle later re-enters under the same reservation and the same
    stall, advancing `occupancy_status` from `OUT_TEMP` back to `CHECKED_IN`".

    Design: Difficulty/non_linear_state_machine/reservation_in_out_cycle_checked_in_out_temp
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L3a", "kind": "SURFACE_LOT", "standard_capacity": 2,
                       "in_out_allowed": True},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    res_id = checked_in["id"]

    validate_success(api_client.gate_exit_reservation(res_id, OPERATOR), 200)
    validate_success(api_client.gate_reentry_reservation(res_id, OPERATOR), 200)
    out_again = validate_success(api_client.gate_exit_reservation(res_id, OPERATOR), 200)
    assert out_again["occupancy_status"] == "OUT_TEMP"

    lot = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert lot["available_standard_count"] == 1


def test_shuttle_branching_cancel_vs_depart():
    """PRD §3.9: "from `SCHEDULED` the operator may cancel the trip, moving `status`
    from `SCHEDULED` to the terminal `CANCELLED`".
    PRD §3.9: "From `BOARDING` the operator departs the trip, moving `status` from
    `BOARDING` to the terminal `DEPARTED`".

    Design: Difficulty/non_linear_state_machine/shuttle_trip_branching_cancel_vs_depart
    """
    set_clock("2026-07-01T09:40:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L3b", "kind": "SURFACE_LOT", "standard_capacity": 2,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    trip_a = create_shuttle_trip(lot["id"], depart_at="2026-07-01T10:00:00Z", seat_capacity=4)
    trip_b = create_shuttle_trip(lot["id"], depart_at="2026-07-01T10:00:00Z", seat_capacity=4)

    cancelled = validate_success(api_client.cancel_shuttle_trip(trip_a["id"], OPERATOR), 200)
    assert cancelled["status"] == "CANCELLED"

    validate_success(api_client.open_boarding_shuttle_trip(trip_b["id"], OPERATOR), 200)
    departed = validate_success(api_client.depart_shuttle_trip(trip_b["id"], OPERATOR), 200)
    assert departed["status"] == "DEPARTED"


# ─── Rule 4: transitive_cascade ──────────────────────────────────────────────
def test_no_show_cascade_releases_stall_and_suspends_customer():
    """PRD §3.7: "The backing stall hold transitions from `HELD` to `RELEASED` and the
    lot's availability counter for that class is recomputed upward by one."
    PRD §3.7: "The booking customer's `no_show_strikes` is increased by one, and if
    that count reaches three the customer's `status` is set to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/no_show_sweep_cascade_depth4_to_customer_suspension
    """
    set_clock("2026-06-30T09:00:00Z")
    customer = get_success_data(api_client.create_customer(
        {"email": "c4a@x.com", "full_name": "C4a"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "L4a", "kind": "SURFACE_LOT", "standard_capacity": 3,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    vehicle = get_success_data(api_client.create_vehicle(
        {"customer_id": customer["id"], "plate": "STD4a", "size_class": "STANDARD",
         "is_ev": False}, ADMIN))

    # Two prior marked no-shows (strikes -> 2), then the third under test (-> 3).
    cycles = [
        ("2026-06-30T09:00:00Z", "2026-06-30T09:05:00Z", "2026-07-01T10:00:00Z", "2026-06-30T09:40:00Z"),
        ("2026-06-30T09:40:00Z", "2026-06-30T09:45:00Z", "2026-07-01T11:00:00Z", "2026-06-30T10:20:00Z"),
    ]
    for book_clock, start, end, ns_clock in cycles:
        set_clock(book_clock)
        live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
        r = get_success_data(api_client.create_reservation(
            {"customer_id": customer["id"], "lot_id": lot["id"], "vehicle_id": vehicle["id"],
             "rate_plan_id": rate_plan["id"], "scheduled_start": start, "scheduled_end": end,
             "prepaid": False, "expected_lot_version": live["version"]}, ADMIN))
        set_clock(ns_clock)
        validate_success(api_client.mark_no_show(r["id"], ADMIN), 200)

    # Fresh third BOOKED reservation, then mark-no-show -> strike 3 -> SUSPENDED.
    set_clock("2026-06-30T10:20:00Z")
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res3 = get_success_data(api_client.create_reservation(
        {"customer_id": customer["id"], "lot_id": lot["id"], "vehicle_id": vehicle["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-06-30T10:25:00Z",
         "scheduled_end": "2026-07-01T12:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN))
    set_clock("2026-06-30T11:00:00Z")
    swept = validate_success(api_client.mark_no_show(res3["id"], OPERATOR), 200)
    assert swept["occupancy_status"] == "NO_SHOW"

    cust_after = get_success_data(api_client.get_customer(customer["id"], ADMIN))
    assert cust_after["no_show_strikes"] == 3
    assert cust_after["status"] == "SUSPENDED"

    lot_after = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    assert lot_after["available_standard_count"] == 3


def test_checkout_cascade_releases_stall_and_shuttle_seat():
    """PRD §3.6: "The backing stall hold transitions from `OCCUPIED` to `RELEASED`, its
    `hold_end` is set to `actual_out`, and the lot's availability counter for that class
    is recomputed upward by one. If the reservation holds a shuttle seat, that trip's
    `seats_taken` is decremented by one and the reservation's `shuttle_trip_id` is
    cleared."

    Design: Difficulty/transitive_cascade/checkout_cascade_depth3_stall_and_shuttle_release
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L4b", "kind": "SURFACE_LOT", "standard_capacity": 2},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z")
    trip = create_shuttle_trip(scenario["lot"]["id"], depart_at="2026-07-01T12:00:00Z",
                               seat_capacity=4)
    assign_reservation_to_trip(reservation["id"], trip["id"])

    set_clock("2026-07-01T10:00:00Z")
    validate_success(api_client.check_in_reservation(reservation["id"], OPERATOR), 200)
    set_clock("2026-07-02T08:00:00Z")
    validate_success(api_client.check_out_reservation(reservation["id"], OPERATOR), 200)

    lot_after = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert lot_after["available_standard_count"] == 2
    trip_after = get_success_data(api_client.get_shuttle_trip(trip["id"], ADMIN))
    assert trip_after["seats_taken"] == 0


# ─── Rule 9 (stall slice): compensating_invariant ────────────────────────────
def test_stall_count_conserved_book_then_cancel():
    """PRD §2.5: "the available count for that class equals that class's capacity minus
    the number of stall holds on the lot whose own stall class matches and whose
    `status` is either `HELD` or `OCCUPIED`. Holds in `RELEASED` status do not consume
    inventory."

    Design: Difficulty/compensating_invariant/stall_count_conserved_book_then_cancel
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L9a", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z")
    validate_success(api_client.cancel_reservation(reservation["id"], ADMIN), 200)
    lot_after = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert lot_after["available_standard_count"] == 5
