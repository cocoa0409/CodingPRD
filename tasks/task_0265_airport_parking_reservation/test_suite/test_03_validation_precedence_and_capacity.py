"""Validation precedence conflicts, cross-entity state dependencies, and the typed
capacity / per-trip-seat overlap semantics.

Queue A (Difficulty) instances for priority_pair_validation_conflict, the zero-count
slice of boundary_precision_check, cross_entity_state_dependency, and
resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_booked_reservation, setup_booking_scenario, book_reservation,
    drive_customer_to_suspended, create_shuttle_trip, assign_reservation_to_trip,
    set_clock, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OPERATOR = TEST_USERS["lot_operator_headers"]


# ─── Rule 5: priority_pair_validation_conflict ───────────────────────────────
def test_suspended_customer_beats_no_stall_capacity_check():
    """PRD §3.3: "In short, the precedence is authentication, then role, then ownership,
    then existence, then cross-reference, then plan quotability, then interval validity,
    then customer suspension, then stale-lot version, and last the per-class stall
    capacity."
    PRD §3.1: "an attempt to create a reservation for a customer whose `status` is
    `SUSPENDED` is rejected with `ERR_CUSTOMER_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_state_beats_no_stall_constraint
    """
    # Drive a customer to SUSPENDED on a strike lot.
    customer, _ = drive_customer_to_suspended()
    cust_check = get_success_data(api_client.get_customer(customer["id"], ADMIN))
    assert cust_check["status"] == "SUSPENDED"

    # A target lot of capacity 1 whose only STANDARD stall is already held by a filler.
    target_lot = get_success_data(api_client.create_lot(
        {"name": "L5a-target", "kind": "SURFACE_LOT", "standard_capacity": 1,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": target_lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    filler = get_success_data(api_client.create_customer(
        {"email": "filler5@x.com", "full_name": "Filler"}, ADMIN))
    filler_veh = get_success_data(api_client.create_vehicle(
        {"customer_id": filler["id"], "plate": "FILL5", "size_class": "STANDARD",
         "is_ev": False}, ADMIN))
    live = get_success_data(api_client.get_lot(target_lot["id"], ADMIN))
    get_success_data(api_client.create_reservation(
        {"customer_id": filler["id"], "lot_id": target_lot["id"], "vehicle_id": filler_veh["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN))

    # The suspect customer needs a vehicle on the target lot too.
    suspect_veh = get_success_data(api_client.create_vehicle(
        {"customer_id": customer["id"], "plate": "STD5a", "size_class": "STANDARD",
         "is_ev": False}, ADMIN))
    live2 = get_success_data(api_client.get_lot(target_lot["id"], ADMIN))
    res = api_client.create_reservation(
        {"customer_id": customer["id"], "lot_id": target_lot["id"],
         "vehicle_id": suspect_veh["id"], "rate_plan_id": rate_plan["id"],
         "scheduled_start": "2026-07-05T10:00:00Z", "scheduled_end": "2026-07-06T10:00:00Z",
         "prepaid": False, "expected_lot_version": live2["version"]}, ADMIN)
    validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=409)


def test_retired_rate_plan_beats_invalid_interval():
    """PRD §3.3: "Then quotability: the rate plan's `active` must be true, ... a
    violation yields `ERR_RATE_PLAN_NOT_QUOTABLE`. Then the interval: `scheduled_end`
    must be strictly after `scheduled_start`, ... a violation yields
    `ERR_INVALID_INTERVAL`."

    Design: Difficulty/priority_pair_validation_conflict/interval_temporal_beats_rate_plan_constraint
    """
    scenario = setup_booking_scenario(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L5b", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    validate_success(api_client.retire_rate_plan(scenario["rate_plan"]["id"], ADMIN), 200)

    # Retired plan AND scheduled_end before scheduled_start -> the quotability error wins.
    res, _ = book_reservation(scenario, scheduled_start="2026-07-02T10:00:00Z",
                              scheduled_end="2026-07-02T08:00:00Z")
    validate_error(res, "ERR_RATE_PLAN_NOT_QUOTABLE", expected_status=422)


# ─── Rule 6 (zero-count slice): boundary_precision_check ──────────────────────
def test_no_stall_available_when_ev_inventory_is_zero():
    """PRD §3.3: "after all of the above pass, the capacity check: the stall class
    derived from the vehicle must have at least one stall available on the lot, else
    `ERR_NO_STALL_AVAILABLE`."

    Design: Difficulty/boundary_precision_check/no_stall_available_at_zero_count_empty_inventory
    """
    set_clock("2026-06-30T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L6b", "kind": "GARAGE", "standard_capacity": 0, "oversized_capacity": 0,
         "ev_capacity": 1, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 3000,
         "ev_surcharge_cents_per_day": 400}, ADMIN))
    c1 = get_success_data(api_client.create_customer({"email": "ev1@x.com", "full_name": "EV One"}, ADMIN))
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "EVA", "size_class": "STANDARD", "is_ev": True}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    get_success_data(api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN))

    c2 = get_success_data(api_client.create_customer({"email": "ev2@x.com", "full_name": "EV Two"}, ADMIN))
    v2 = get_success_data(api_client.create_vehicle(
        {"customer_id": c2["id"], "plate": "EVB", "size_class": "STANDARD", "is_ev": True}, ADMIN))
    live2 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    assert live2["available_ev_count"] == 0
    res = api_client.create_reservation(
        {"customer_id": c2["id"], "lot_id": lot["id"], "vehicle_id": v2["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T12:00:00Z",
         "scheduled_end": "2026-07-02T12:00:00Z", "prepaid": False,
         "expected_lot_version": live2["version"]}, ADMIN)
    validate_error(res, "ERR_NO_STALL_AVAILABLE", expected_status=409)


# ─── Rule 7: cross_entity_state_dependency ───────────────────────────────────
def test_booking_blocked_when_customer_suspended():
    """PRD §3.1: "A suspended customer cannot book or prepay: an attempt to create a
    reservation for a customer whose `status` is `SUSPENDED` is rejected with
    `ERR_CUSTOMER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_customer_active_reservation_lot
    """
    customer, _ = drive_customer_to_suspended()
    cust_check = get_success_data(api_client.get_customer(customer["id"], ADMIN))
    assert cust_check["status"] == "SUSPENDED"

    lot = get_success_data(api_client.create_lot(
        {"name": "L7a", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    veh = get_success_data(api_client.create_vehicle(
        {"customer_id": customer["id"], "plate": "STD7a", "size_class": "STANDARD",
         "is_ev": False}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res = api_client.create_reservation(
        {"customer_id": customer["id"], "lot_id": lot["id"], "vehicle_id": veh["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-10T10:00:00Z",
         "scheduled_end": "2026-07-11T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN)
    validate_error(res, "ERR_CUSTOMER_SUSPENDED", expected_status=409)


def test_assign_shuttle_to_departed_trip_rejected():
    """PRD §3.9: "The trip must serve the reservation's lot, must be in `SCHEDULED` or
    `BOARDING` status, and must have `seats_taken` strictly below `seat_capacity`; if
    any of these fails — the trip is full, does not serve the lot, or is not in a
    seat-accepting state — the assignment is rejected with `ERR_SHUTTLE_FULL`."

    Design: Difficulty/cross_entity_state_dependency/assign_shuttle_requires_trip_serves_lot_and_open
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L7b", "kind": "SURFACE_LOT", "standard_capacity": 3},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-02T10:00:00Z", scheduled_end="2026-07-03T10:00:00Z")
    trip = create_shuttle_trip(scenario["lot"]["id"], depart_at="2026-07-01T10:00:00Z",
                               seat_capacity=4)
    set_clock("2026-07-01T09:40:00Z")
    validate_success(api_client.open_boarding_shuttle_trip(trip["id"], OPERATOR), 200)
    departed = validate_success(api_client.depart_shuttle_trip(trip["id"], OPERATOR), 200)
    assert departed["status"] == "DEPARTED"

    res = api_client.assign_shuttle(
        reservation["id"],
        {"shuttle_trip_id": trip["id"], "expected_shuttle_trip_version": departed["version"]},
        ADMIN)
    validate_error(res, "ERR_SHUTTLE_FULL", expected_status=409)


# ─── Rule 8: resource_temporal_overlap ───────────────────────────────────────
def test_stall_capacity_overlap_is_aggregate_count():
    """PRD §2.5: "the available count for that class equals that class's capacity minus
    the number of stall holds on the lot whose own stall class matches and whose
    `status` is either `HELD` or `OCCUPIED`."
    PRD §3.3: "the stall class derived from the vehicle must have at least one stall
    available on the lot, else `ERR_NO_STALL_AVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/stall_capacity_overlap_aggregate_count
    """
    set_clock("2026-06-30T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L8a", "kind": "SURFACE_LOT", "standard_capacity": 1,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    c1 = get_success_data(api_client.create_customer({"email": "c8a1@x.com", "full_name": "C8a1"}, ADMIN))
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "S8a1", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    get_success_data(api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-03T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN))

    c2 = get_success_data(api_client.create_customer({"email": "c8a2@x.com", "full_name": "C8a2"}, ADMIN))
    v2 = get_success_data(api_client.create_vehicle(
        {"customer_id": c2["id"], "plate": "S8a2", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live2 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    # Distinct overlapping interval, but the single stall is already consumed.
    res = api_client.create_reservation(
        {"customer_id": c2["id"], "lot_id": lot["id"], "vehicle_id": v2["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-02T10:00:00Z",
         "scheduled_end": "2026-07-04T10:00:00Z", "prepaid": False,
         "expected_lot_version": live2["version"]}, ADMIN)
    validate_error(res, "ERR_NO_STALL_AVAILABLE", expected_status=409)


def test_shuttle_seat_capacity_overlap_per_trip():
    """PRD §3.9: "A trip is born in `SCHEDULED` status with `seats_taken` of 0; its
    `seats_taken` may never exceed its `seat_capacity`."
    PRD §3.9: "must have `seats_taken` strictly below `seat_capacity`; if any of these
    fails — the trip is full ... — the assignment is rejected with `ERR_SHUTTLE_FULL`."

    Design: Difficulty/resource_temporal_overlap/shuttle_seat_capacity_overlap_per_trip
    """
    set_clock("2026-06-30T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "L8b", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    trip = create_shuttle_trip(lot["id"], depart_at="2026-07-01T12:00:00Z", seat_capacity=1)

    c1 = get_success_data(api_client.create_customer({"email": "c8b1@x.com", "full_name": "C8b1"}, ADMIN))
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "S8b1", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res1 = get_success_data(api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-02T10:00:00Z",
         "scheduled_end": "2026-07-03T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN))
    assign_reservation_to_trip(res1["id"], trip["id"])

    c2 = get_success_data(api_client.create_customer({"email": "c8b2@x.com", "full_name": "C8b2"}, ADMIN))
    v2 = get_success_data(api_client.create_vehicle(
        {"customer_id": c2["id"], "plate": "S8b2", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live2 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res2 = get_success_data(api_client.create_reservation(
        {"customer_id": c2["id"], "lot_id": lot["id"], "vehicle_id": v2["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-02T11:00:00Z",
         "scheduled_end": "2026-07-03T11:00:00Z", "prepaid": False,
         "expected_lot_version": live2["version"]}, ADMIN))

    trip_now = get_success_data(api_client.get_shuttle_trip(trip["id"], ADMIN))
    assert trip_now["seats_taken"] == 1 == trip_now["seat_capacity"]
    res = api_client.assign_shuttle(
        res2["id"],
        {"shuttle_trip_id": trip["id"], "expected_shuttle_trip_version": trip_now["version"]},
        ADMIN)
    validate_error(res, "ERR_SHUTTLE_FULL", expected_status=409)
