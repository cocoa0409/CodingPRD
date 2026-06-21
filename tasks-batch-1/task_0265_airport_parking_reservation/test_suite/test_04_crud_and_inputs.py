"""CRUD surface, required/optional/typed input validation, computed fields, immutability,
and referential existence.

Queue B (Corner) instances from the entities and validations sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    assert_lot, assert_vehicle, assert_reservation, assert_payment_txn, find_txn,
    setup_booking_scenario, book_reservation, create_booked_reservation, set_clock,
    NON_EXISTENT_UUID, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]


# ─── entities ────────────────────────────────────────────────────────────────
def test_create_lot_returns_201_with_initialized_counters():
    """PRD §2.5: "When a lot is first created, each available counter is initialized to
    the matching capacity, since no holds exist yet."
    PRD §2.4: "an integer `version` that begins at its initial value on creation".

    Design: Corner/entities/create_lot_returns_201_with_initialized_counters
    """
    set_clock("2026-06-30T09:00:00Z")
    res = api_client.create_lot(
        {"name": "L-create", "kind": "GARAGE", "standard_capacity": 10,
         "oversized_capacity": 4, "ev_capacity": 2, "in_out_allowed": True}, ADMIN)
    lot = validate_success(res, 201)
    assert_lot(lot)
    assert lot["available_standard_count"] == 10
    assert lot["available_oversized_count"] == 4
    assert lot["available_ev_count"] == 2
    assert lot["version"] == 1


def test_get_reservation_returns_stored_entity():
    """PRD §3.3: "The reservation begins with `occupancy_status` of `BOOKED`,
    `settlement_status` of `UNSETTLED`".

    Design: Corner/entities/get_reservation_returns_stored_entity
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lce1", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    fetched = validate_success(api_client.get_reservation(reservation["id"], ADMIN), 200)
    assert fetched["occupancy_status"] == "BOOKED"
    assert fetched["settlement_status"] == "UNSETTLED"


def test_list_lots_paginated_envelope():
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    bookkeeping fields `limit`, `offset`, `total_count`, and `has_more`, where
    `total_count` is the number of matching resources before paging and `has_more`
    indicates whether further pages remain."

    Design: Corner/entities/list_lots_paginated_envelope
    """
    set_clock("2026-06-30T09:00:00Z")
    api_client.create_lot({"name": "Lp1", "kind": "SURFACE_LOT", "standard_capacity": 1,
                           "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN)
    api_client.create_lot({"name": "Lp2", "kind": "GARAGE", "standard_capacity": 2,
                           "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN)
    data, meta = validate_paginated(api_client.list_lots(ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_get_lot_not_found_returns_404():
    """PRD §2.8: "the system validates each path identifier from left to right and
    rejects the first one that does not resolve to an existing resource with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_lot_not_found_returns_404
    """
    set_clock("2026-06-30T09:00:00Z")
    res = api_client.get_lot(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_reservation_missing_required_field_returns_validation():
    """PRD §2.8: "a request that omits a required field, supplies a field of the wrong
    type, or supplies an invalid value for an enumerated field ... is rejected with
    `ERR_VALIDATION`."

    Design: Corner/entities/create_reservation_missing_required_field_returns_validation
    """
    scenario = setup_booking_scenario(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lcrv", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    lot = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    # Omit scheduled_end (a required input).
    res = api_client.create_reservation(
        {"customer_id": scenario["customer"]["id"], "lot_id": lot["id"],
         "vehicle_id": scenario["vehicle"]["id"], "rate_plan_id": scenario["rate_plan"]["id"],
         "scheduled_start": "2026-07-01T10:00:00Z", "expected_lot_version": lot["version"]}, ADMIN)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_vehicle_default_is_ev_false_applied():
    """PRD §3.1: "The `is_ev` flag marks a vehicle that needs an EV-charging stall and
    defaults to false when omitted."

    Design: Corner/entities/vehicle_default_is_ev_false_applied
    """
    set_clock("2026-06-30T09:00:00Z")
    customer = get_success_data(api_client.create_customer(
        {"email": "cvd@x.com", "full_name": "CVD"}, ADMIN))
    res = api_client.create_vehicle(
        {"customer_id": customer["id"], "plate": "VDEF", "size_class": "STANDARD"}, ADMIN)
    vehicle = validate_success(res, 201)
    assert vehicle["is_ev"] is False


def test_reservation_stall_class_computed_from_vehicle_ev():
    """PRD §3.3: "The reservation's `stall_class` is derived from the vehicle, not
    supplied: it is `EV` if the vehicle's `is_ev` is true; otherwise `OVERSIZED` if the
    vehicle's `size_class` is `OVERSIZED`; otherwise `STANDARD`."

    Design: Corner/entities/reservation_stall_class_computed_from_vehicle_ev
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lev", "kind": "GARAGE", "standard_capacity": 0,
                       "oversized_capacity": 0, "ev_capacity": 2},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 3000,
                             "ev_surcharge_cents_per_day": 400},
        vehicle_overrides={"plate": "EVX", "size_class": "STANDARD", "is_ev": True})
    assert reservation["stall_class"] == "EV"
    lot = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert lot["available_ev_count"] == 1


def test_create_vehicle_invalid_size_class_enum_rejected():
    """PRD §2.8: "supplies an invalid value for an enumerated field (for example a
    `size_class`, `kind`, or `rate_mode` outside its allowed set) is rejected with
    `ERR_VALIDATION`."

    Design: Corner/entities/create_vehicle_invalid_size_class_enum_rejected
    """
    set_clock("2026-06-30T09:00:00Z")
    customer = get_success_data(api_client.create_customer(
        {"email": "cven@x.com", "full_name": "CVEN"}, ADMIN))
    res = api_client.create_vehicle(
        {"customer_id": customer["id"], "plate": "BADENUM", "size_class": "HUGE",
         "is_ev": False}, ADMIN)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_payment_txn_immutable_no_version_field():
    """PRD §2.4: "a payment transaction is immutable once written. A payment transaction
    therefore carries only `id` and `created_at` — it has no `updated_at` field and no
    `version` field."
    PRD §3.3: "records a payment transaction of kind `AUTHORIZATION` for the full
    `provisional_quote_cents`".

    Design: Corner/entities/paymenttxn_immutable_no_version_field
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lpt", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        prepaid=True)
    txns = get_success_data(api_client.list_reservation_payment_txns(reservation["id"], ADMIN))
    auth = find_txn(txns, "AUTHORIZATION")
    assert auth is not None
    assert_payment_txn(auth)
    # AUTHORIZATION captures the full provisional quote (PRD §3.3). HOURLY 300/cap 2000
    # over exactly one day = min(24*300, 2000) = 2000.
    assert auth["amount_cents"] == reservation["provisional_quote_cents"]
    assert auth["amount_cents"] == 2000


def test_create_vehicle_nonexistent_customer_returns_404():
    """PRD §2.8: "The same existence rule governs every foreign key referenced in a
    request body: if a booking names a lot, vehicle, rate plan, or customer that does
    not exist — or any other endpoint references a resource that does not exist — the
    request fails with `ERR_NOT_FOUND` before any business rule is evaluated."

    Design: Corner/entities/create_vehicle_nonexistent_customer_returns_404
    """
    set_clock("2026-06-30T09:00:00Z")
    res = api_client.create_vehicle(
        {"customer_id": NON_EXISTENT_UUID, "plate": "ORPHAN", "size_class": "STANDARD",
         "is_ev": False}, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ─── validations ─────────────────────────────────────────────────────────────
def test_cross_reference_vehicle_not_owned_by_customer():
    """PRD §3.3: "Next come the cross-reference checks: the named vehicle's
    `customer_id` must equal the booking's `customer_id`, and the named rate plan's
    `lot_id` must equal the booking's `lot_id`; either mismatch yields
    `ERR_CROSS_REFERENCE_MISMATCH`."

    Design: Corner/validations/cross_reference_vehicle_not_owned_by_customer
    """
    set_clock("2026-06-30T09:00:00Z")
    cust_a = get_success_data(api_client.create_customer({"email": "cxa@x.com", "full_name": "CXA"}, ADMIN))
    cust_b = get_success_data(api_client.create_customer({"email": "cxb@x.com", "full_name": "CXB"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "Lxr", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    veh_b = get_success_data(api_client.create_vehicle(
        {"customer_id": cust_b["id"], "plate": "BVEH", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res = api_client.create_reservation(
        {"customer_id": cust_a["id"], "lot_id": lot["id"], "vehicle_id": veh_b["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN)
    validate_error(res, "ERR_CROSS_REFERENCE_MISMATCH", expected_status=422)


def test_valet_plan_on_non_valet_garage_rejected():
    """PRD §3.3: "Then quotability: the rate plan's `active` must be true, and if its
    `rate_mode` is `VALET` the lot's `kind` must be `VALET_GARAGE`; a violation yields
    `ERR_RATE_PLAN_NOT_QUOTABLE`."

    Design: Corner/validations/valet_plan_on_non_valet_garage_rejected
    """
    scenario = setup_booking_scenario(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lvn", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "VALET", "hourly_cents": 300, "daily_cap_cents": 2000,
                             "valet_surcharge_cents": 1500})
    res, _ = book_reservation(scenario, scheduled_start="2026-07-01T10:00:00Z",
                              scheduled_end="2026-07-02T10:00:00Z")
    validate_error(res, "ERR_RATE_PLAN_NOT_QUOTABLE", expected_status=422)


def test_invalid_interval_end_not_after_start():
    """PRD §3.3: "Then the interval: `scheduled_end` must be strictly after
    `scheduled_start`, and `scheduled_start` must be strictly after the current clock;
    a violation yields `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/invalid_interval_end_not_after_start
    """
    scenario = setup_booking_scenario(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Liv", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    res, _ = book_reservation(scenario, scheduled_start="2026-07-01T10:00:00Z",
                              scheduled_end="2026-07-01T10:00:00Z")
    validate_error(res, "ERR_INVALID_INTERVAL", expected_status=422)


def test_existence_nonexistent_rate_plan_on_create_404():
    """PRD §2.8: "if a booking names a lot, vehicle, rate plan, or customer that does
    not exist ... the request fails with `ERR_NOT_FOUND` before any business rule is
    evaluated."

    Design: Corner/validations/existence_nonexistent_rate_plan_on_create_404
    """
    set_clock("2026-06-30T09:00:00Z")
    customer = get_success_data(api_client.create_customer({"email": "cen@x.com", "full_name": "CEN"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "Len", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    veh = get_success_data(api_client.create_vehicle(
        {"customer_id": customer["id"], "plate": "STDen", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res = api_client.create_reservation(
        {"customer_id": customer["id"], "lot_id": lot["id"], "vehicle_id": veh["id"],
         "rate_plan_id": NON_EXISTENT_UUID, "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
