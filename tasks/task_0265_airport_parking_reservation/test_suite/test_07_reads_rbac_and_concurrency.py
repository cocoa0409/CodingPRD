"""FK reverse-reachability reads, reinstatement, RBAC denials, optimistic-concurrency
stale-version rejections, denormalized counter reconciliation, and immediate quote
visibility.

Queue B (Corner) instances from the endpoints, rbac, cross_cutting, and
consistency_model sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_booked_reservation, drive_customer_to_suspended, set_clock,
    make_customer_headers, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OPERATOR = TEST_USERS["lot_operator_headers"]


# ─── endpoints ───────────────────────────────────────────────────────────────
def test_fk_reverse_rate_plans_by_lot():
    """PRD §3.10: "Child collections are reached through their parent: a lot's rate
    plans, cancellation policies, stall holds, and shuttle trips".

    Design: Corner/endpoints/fk_reverse_rate_plans_by_lot
    """
    set_clock("2026-06-30T09:00:00Z")
    lot = get_success_data(api_client.create_lot(
        {"name": "Lfr", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    api_client.create_rate_plan({"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN)
    api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2500}, ADMIN)
    data, meta = validate_paginated(api_client.list_lot_rate_plans(lot["id"], ADMIN))
    assert meta["total_count"] == 2


def test_fk_reverse_reservations_by_lot_filter():
    """PRD §3.10: "The reservation list may be narrowed by `lot_id`, `vehicle_id`,
    `rate_plan_id`, or `shuttle_trip_id`, returning only reservations whose
    corresponding reference matches."

    Design: Corner/endpoints/fk_reverse_reservations_by_lot_filter
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lflt", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000})
    data, meta = validate_paginated(
        api_client.list_reservations(ADMIN, params={"lot_id": scenario["lot"]["id"]}))
    assert meta["total_count"] == 1


def test_customer_reinstate_clears_strikes():
    """PRD §3.1: "A `FacilityAdmin` can lift a suspension by reinstating the customer,
    which resets `no_show_strikes` back to 0 and restores `status` to `ACTIVE`;
    reinstatement increments the customer's `version` by one."

    Design: Corner/endpoints/customer_reinstate_clears_strikes
    """
    customer, _ = drive_customer_to_suspended()
    suspended = get_success_data(api_client.get_customer(customer["id"], ADMIN))
    assert suspended["status"] == "SUSPENDED"

    reinstated = validate_success(api_client.reinstate_customer(customer["id"], ADMIN), 200)
    assert reinstated["status"] == "ACTIVE"
    assert reinstated["no_show_strikes"] == 0


# ─── rbac ────────────────────────────────────────────────────────────────────
def test_customer_cannot_check_in_forbidden_role():
    """PRD §2.1: "When a request carries valid headers but the named role is not
    permitted to perform the requested operation, the response is `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "A `LotOperator` works the gate (check-in, check-out, temporary exit,
    re-entry, manual no-show)".

    Design: Corner/rbac/customer_cannot_check_in_forbidden_role
    """
    set_clock("2026-06-30T09:00:00Z")
    customer = get_success_data(api_client.create_customer(
        {"email": "crb@x.com", "full_name": "CRB"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "Lrb", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    cust_headers = make_customer_headers(customer["id"])
    veh = get_success_data(api_client.create_vehicle(
        {"customer_id": customer["id"], "plate": "STDrb", "size_class": "STANDARD",
         "is_ev": False}, cust_headers))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    reservation = get_success_data(api_client.create_reservation(
        {"customer_id": customer["id"], "lot_id": lot["id"], "vehicle_id": veh["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, cust_headers))
    set_clock("2026-07-01T10:00:00Z")
    res = api_client.check_in_reservation(reservation["id"], cust_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_customer_cannot_cancel_other_customers_reservation():
    """PRD §2.1: "a `Customer` may only cancel a reservation, assign a shuttle to a
    reservation, register a vehicle, or list a customer's own reservations and vehicles
    when the relevant `customer_id` equals `X-User-ID`; a mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_cancel_other_customers_reservation
    """
    set_clock("2026-06-30T09:00:00Z")
    cust_a = get_success_data(api_client.create_customer({"email": "cowa@x.com", "full_name": "COWA"}, ADMIN))
    cust_b = get_success_data(api_client.create_customer({"email": "cowb@x.com", "full_name": "COWB"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "Low", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    a_headers = make_customer_headers(cust_a["id"])
    veh_a = get_success_data(api_client.create_vehicle(
        {"customer_id": cust_a["id"], "plate": "STDow", "size_class": "STANDARD",
         "is_ev": False}, a_headers))
    live = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res_a = get_success_data(api_client.create_reservation(
        {"customer_id": cust_a["id"], "lot_id": lot["id"], "vehicle_id": veh_a["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live["version"]}, a_headers))

    b_headers = make_customer_headers(cust_b["id"])
    res = api_client.cancel_reservation(res_a["id"], b_headers)
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "Every request to the API must be authenticated through two mandatory
    HTTP headers: `X-User-ID` ... and `X-User-Role` .... If either header is missing,
    or if `X-User-Role` does not name a role the system recognizes, the request is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    set_clock("2026-06-30T09:00:00Z")
    api_client.create_lot({"name": "Lna", "kind": "SURFACE_LOT", "standard_capacity": 1,
                           "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN)
    res = api_client.list_lots({})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ─── cross_cutting ───────────────────────────────────────────────────────────
def test_occ_stale_lot_version_on_reservation_create():
    """PRD §2.6: "If `expected_lot_version` does not equal the lot's current `version` —
    because another booking has since consumed inventory on the same lot and advanced
    its version — the create is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting/occ_stale_lot_version_on_reservation_create
    """
    set_clock("2026-06-30T09:00:00Z")
    c1 = get_success_data(api_client.create_customer({"email": "co1@x.com", "full_name": "CO1"}, ADMIN))
    c2 = get_success_data(api_client.create_customer({"email": "co2@x.com", "full_name": "CO2"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "Locc", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "OCC1", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    v2 = get_success_data(api_client.create_vehicle(
        {"customer_id": c2["id"], "plate": "OCC2", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    stale_version = lot["version"]

    get_success_data(api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": stale_version}, ADMIN))

    # Second create still carries the pre-advance version -> stale.
    res = api_client.create_reservation(
        {"customer_id": c2["id"], "lot_id": lot["id"], "vehicle_id": v2["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T11:00:00Z",
         "scheduled_end": "2026-07-02T11:00:00Z", "prepaid": False,
         "expected_lot_version": stale_version}, ADMIN)
    validate_error(res, "ERR_STALE_LOT_VERSION", expected_status=412)


def test_occ_stale_shuttle_version_on_assign():
    """PRD §2.6: "If `expected_shuttle_trip_version` does not equal the trip's current
    `version` — because another assignment has since taken a seat on the same trip and
    advanced its version — the assignment is rejected with `ERR_STALE_SHUTTLE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_shuttle_version_on_assign
    """
    set_clock("2026-06-30T09:00:00Z")
    c1 = get_success_data(api_client.create_customer({"email": "cs1@x.com", "full_name": "CS1"}, ADMIN))
    c2 = get_success_data(api_client.create_customer({"email": "cs2@x.com", "full_name": "CS2"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "Lsv", "kind": "SURFACE_LOT", "standard_capacity": 5,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    trip = get_success_data(api_client.create_shuttle_trip(
        {"lot_id": lot["id"], "depart_at": "2026-07-01T12:00:00Z", "seat_capacity": 4}, ADMIN))
    trip_stale_version = trip["version"]
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "SV1", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    v2 = get_success_data(api_client.create_vehicle(
        {"customer_id": c2["id"], "plate": "SV2", "size_class": "STANDARD", "is_ev": False}, ADMIN))

    live1 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res1 = get_success_data(api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-02T10:00:00Z",
         "scheduled_end": "2026-07-03T10:00:00Z", "prepaid": False,
         "expected_lot_version": live1["version"]}, ADMIN))
    live2 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    res2 = get_success_data(api_client.create_reservation(
        {"customer_id": c2["id"], "lot_id": lot["id"], "vehicle_id": v2["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-02T11:00:00Z",
         "scheduled_end": "2026-07-03T11:00:00Z", "prepaid": False,
         "expected_lot_version": live2["version"]}, ADMIN))

    # First assign advances the trip version.
    get_success_data(api_client.assign_shuttle(
        res1["id"], {"shuttle_trip_id": trip["id"], "expected_shuttle_trip_version": trip_stale_version}, ADMIN))
    # Second assign still carries the pre-advance trip version -> stale.
    res = api_client.assign_shuttle(
        res2["id"], {"shuttle_trip_id": trip["id"], "expected_shuttle_trip_version": trip_stale_version}, ADMIN)
    validate_error(res, "ERR_STALE_SHUTTLE_VERSION", expected_status=412)


def test_derived_lot_counter_reconciles_after_double_booking():
    """PRD §2.5: "The counters are denormalized projections of the active holds against
    each pool, and they are reconciled in-band on every stall-hold create and every
    stall-hold release."

    Design: Corner/cross_cutting/derived_lot_counter_reconciles_after_double_booking
    """
    set_clock("2026-06-30T09:00:00Z")
    c1 = get_success_data(api_client.create_customer({"email": "cdr1@x.com", "full_name": "CDR1"}, ADMIN))
    c2 = get_success_data(api_client.create_customer({"email": "cdr2@x.com", "full_name": "CDR2"}, ADMIN))
    lot = get_success_data(api_client.create_lot(
        {"name": "Ldr", "kind": "SURFACE_LOT", "standard_capacity": 3,
         "oversized_capacity": 0, "ev_capacity": 0, "in_out_allowed": False}, ADMIN))
    rate_plan = get_success_data(api_client.create_rate_plan(
        {"lot_id": lot["id"], "rate_mode": "DAILY", "daily_cap_cents": 2000}, ADMIN))
    v1 = get_success_data(api_client.create_vehicle(
        {"customer_id": c1["id"], "plate": "DR1", "size_class": "STANDARD", "is_ev": False}, ADMIN))
    v2 = get_success_data(api_client.create_vehicle(
        {"customer_id": c2["id"], "plate": "DR2", "size_class": "STANDARD", "is_ev": False}, ADMIN))

    live0 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    get_success_data(api_client.create_reservation(
        {"customer_id": c1["id"], "lot_id": lot["id"], "vehicle_id": v1["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T10:00:00Z",
         "scheduled_end": "2026-07-02T10:00:00Z", "prepaid": False,
         "expected_lot_version": live0["version"]}, ADMIN))
    live1 = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    get_success_data(api_client.create_reservation(
        {"customer_id": c2["id"], "lot_id": lot["id"], "vehicle_id": v2["id"],
         "rate_plan_id": rate_plan["id"], "scheduled_start": "2026-07-01T11:00:00Z",
         "scheduled_end": "2026-07-02T11:00:00Z", "prepaid": False,
         "expected_lot_version": live1["version"]}, ADMIN))

    lot_after = get_success_data(api_client.get_lot(lot["id"], ADMIN))
    assert lot_after["available_standard_count"] == 1


# ─── consistency_model ───────────────────────────────────────────────────────
def test_immediate_visibility_of_quote_in_create_response():
    """PRD §3.3: "The provisional charge is then computed over the planned interval and
    reduced by any prepay discount, yielding `provisional_quote_cents`".

    Design: Corner/consistency_model/immediate_visibility_of_quote_in_create_response
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lim", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-03T10:00:00Z")
    # The create response itself carried the quote (create_booked_reservation returns it).
    assert reservation["provisional_quote_cents"] == 4000
