"""Assignment eligibility battery, resource occupation conflicts, start window,
and optimistic concurrency on order assignment."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, make_customer, make_vehicle, make_driver, make_quote,
    price_quote, accept_quote, pay_full_deposit, get_order, get_vehicle,
    get_driver, assign_order, setup_pending_deposit_order,
    setup_confirmed_order, setup_assigned_order,
)

DISPATCH = TEST_USERS["dispatch_manager_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


def _assign_attempt(order_id, vehicle_id, driver_id, version=None):
    order = get_order(order_id)
    payload = {"vehicle_id": vehicle_id, "driver_id": driver_id,
               "expected_order_version": version if version is not None
               else order["version"]}
    return api_client.assign_order(order_id, payload, DISPATCH)


class TestStateMasksDomainChecks:
    def test_assign_pending_deposit_order_returns_invalid_state(self, api):
        """PRD §2.8: "4. State validity: the target entity is in a state from
        which the requested transition exists per Section 3, else
        `ERR_INVALID_STATE` (HTTP 409)." runs before "5. Domain rules, in their
        declared priority", and "Earlier failures mask later ones".

        Order still in PENDING_DEPOSIT: assignment must fail with
        ERR_INVALID_STATE regardless of any domain-check outcome.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_assign
        """
        ctx = setup_pending_deposit_order()
        vehicle = make_vehicle()
        driver = make_driver()
        res = _assign_attempt(ctx["order"]["id"], vehicle["id"], driver["id"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_assign_already_assigned_order_returns_invalid_state(self, api):
        """PRD §2.8: "4. State validity: the target entity is in a state from
        which the requested transition exists per Section 3, else
        `ERR_INVALID_STATE` (HTTP 409)." Assignment is the `CONFIRMED` →
        `ASSIGNED` transition (PRD §3.4); an order already in `ASSIGNED` has no
        such transition.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_assign
        """
        ctx = setup_assigned_order()
        vehicle2 = make_vehicle()
        driver2 = make_driver()
        res = _assign_attempt(ctx["order"]["id"], vehicle2["id"], driver2["id"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestCrossEntityStateDependency:
    def test_assign_vehicle_in_maintenance_rejected(self, api):
        """PRD §3.4: "On the vehicle side: the named vehicle must exist and stand
        `AVAILABLE`". A coach in `IN_MAINTENANCE` does not stand `AVAILABLE`, so
        the requested transition does not exist — "else `ERR_INVALID_STATE`
        (HTTP 409)" (PRD §2.8 step 4).

        Design: Difficulty/cross_entity_state_dependency/order_assign_requires_vehicle_available
        """
        ctx = setup_confirmed_order()
        vehicle = make_vehicle()
        driver = make_driver()
        validate_success(api.send_vehicle_to_maintenance(vehicle["id"], FLEET))
        res = _assign_attempt(ctx["order"]["id"], vehicle["id"], driver["id"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_assign_suspended_driver_rejected(self, api):
        """PRD §3.4: "On the driver side: the named driver must exist and stand
        `AVAILABLE`". PRD §3.2: "From `AVAILABLE` it always succeeds; from
        `ON_DUTY_NOT_DRIVING` it succeeds only when no order in `ASSIGNED` or
        `IN_PROGRESS` names the driver as its primary driver". A `SUSPENDED`
        driver does not stand `AVAILABLE`, so the assignment transition does not
        exist — "else `ERR_INVALID_STATE` (HTTP 409)" (PRD §2.8 step 4).

        Design: Difficulty/cross_entity_state_dependency/order_assign_requires_vehicle_available
        """
        ctx = setup_confirmed_order()
        vehicle = make_vehicle()
        driver = make_driver()
        validate_success(api.suspend_driver(driver["id"],
                                            {"reason": "Policy violation"},
                                            SAFETY))
        assert get_driver(driver["id"])["status"] == "SUSPENDED"
        res = _assign_attempt(ctx["order"]["id"], vehicle["id"], driver["id"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestResourceOccupationConflict:
    def _two_confirmed_orders(self):
        set_clock()
        customer = make_customer(company_name="Overlap Test")
        orders = []
        for i in range(2):
            quote = make_quote(customer["id"], estimated_miles=300,
                               estimated_hours=5)
            quote = price_quote(quote["id"])
            order = accept_quote(quote["id"], customer["id"])
            order = pay_full_deposit(order["id"], customer["id"])
            orders.append(order)
        return customer, orders

    def test_same_vehicle_cannot_be_assigned_twice(self, api):
        """PRD §3.4: "the named vehicle must exist and stand `AVAILABLE`" and a
        successful assignment "moves the vehicle `AVAILABLE` → `ASSIGNED`". A
        vehicle already `ASSIGNED` to one order no longer stands `AVAILABLE`, so
        assigning it to a second order fails state validity — "else
        `ERR_INVALID_STATE` (HTTP 409)" (PRD §2.8 step 4).

        Design: Difficulty/resource_temporal_overlap/vehicle_assignment_conflict_same_vehicle
        """
        _, orders = self._two_confirmed_orders()
        vehicle = make_vehicle()
        driver_a = make_driver()
        assign_order(orders[0]["id"], vehicle["id"], driver_a["id"])
        driver_b = make_driver()
        res = _assign_attempt(orders[1]["id"], vehicle["id"], driver_b["id"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_vehicle(vehicle["id"])["status"] == "ASSIGNED"

    def test_same_driver_cannot_be_assigned_twice(self, api):
        """PRD §3.4: "the named driver must exist and stand `AVAILABLE`" and a
        successful assignment "moves each assigned driver `AVAILABLE` →
        `ON_DUTY_NOT_DRIVING`". A driver already `ON_DUTY_NOT_DRIVING` on one
        order no longer stands `AVAILABLE` for the next — "else
        `ERR_INVALID_STATE` (HTTP 409)" (PRD §2.8 step 4).

        Design: Difficulty/resource_temporal_overlap/vehicle_assignment_conflict_same_vehicle
        """
        _, orders = self._two_confirmed_orders()
        vehicle_a = make_vehicle()
        vehicle_b = make_vehicle()
        driver = make_driver()
        assign_order(orders[0]["id"], vehicle_a["id"], driver["id"])
        res = _assign_attempt(orders[1]["id"], vehicle_b["id"], driver["id"])
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        assert get_driver(driver["id"])["status"] == "ON_DUTY_NOT_DRIVING"


class TestAssignmentEligibilityBattery:
    def test_inspection_expired_before_trip_rejected(self, api):
        """PRD §3.4: "its `dot_inspection_expiry` must fall after the trip date,
        else `ERR_INSPECTION_EXPIRED`".

        Design: Corner/validations/error_inspection_expired_on_assign
        """
        ctx = setup_confirmed_order()
        vehicle = make_vehicle(dot_inspection_expiry="2026-08-15T00:00:00Z")
        driver = make_driver()
        res = _assign_attempt(ctx["order"]["id"], vehicle["id"], driver["id"])
        validate_error(res, ApiErrorId.ERR_INSPECTION_EXPIRED)

    def test_capacity_smaller_than_passengers_rejected(self, api):
        """PRD §3.4: "its `seating_capacity` must be at least the quote's
        `passenger_count`, else `ERR_CAPACITY_EXCEEDED`".

        Design: Corner/validations/error_capacity_exceeded_on_assign
        """
        set_clock()
        customer = make_customer(company_name="Cap Test")
        quote = make_quote(customer["id"], passenger_count=50)
        quote = price_quote(quote["id"])
        order = accept_quote(quote["id"], customer["id"])
        order = pay_full_deposit(order["id"], customer["id"])
        vehicle = make_vehicle(seating_capacity=30)
        driver = make_driver()
        res = _assign_attempt(order["id"], vehicle["id"], driver["id"])
        validate_error(res, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_non_ada_vehicle_for_ada_quote_rejected(self, api):
        """PRD §3.4: "whenever the quote's `ada_required` is set the coach must be
        lift-equipped, else `ERR_ADA_REQUIRED`".

        Design: Corner/validations/error_ada_required_on_assign
        """
        set_clock()
        customer = make_customer(company_name="ADA Test")
        quote = make_quote(customer["id"], ada_required=True)
        quote = price_quote(quote["id"])
        order = accept_quote(quote["id"], customer["id"])
        order = pay_full_deposit(order["id"], customer["id"])
        vehicle = make_vehicle(ada_accessible=False)
        driver = make_driver()
        res = _assign_attempt(order["id"], vehicle["id"], driver["id"])
        validate_error(res, ApiErrorId.ERR_ADA_REQUIRED)


class TestStartTripWindow:
    def test_start_more_than_one_hour_early_rejected(self, api):
        """PRD §3.4: "Thereafter the trip may start — `ASSIGNED` → `IN_PROGRESS`
        — no earlier than one hour before the scheduled `trip_date`; an earlier
        start attempt is rejected with `ERR_TRIP_NOT_YET`."

        Clock at 2026-09-10T06:00Z, trip_date 2026-09-10T08:00Z -> two hours
        early.

        Design: Corner/errors/error_trip_not_yet_on_start
        """
        ctx = setup_assigned_order(
            quote_overrides={"trip_date": "2026-09-10T08:00:00Z",
                             "return_date": "2026-09-10T16:00:00Z"})
        set_clock("2026-09-10T06:00:00Z")
        res = api.start_trip(ctx["order"]["id"], DISPATCH)
        validate_error(res, ApiErrorId.ERR_TRIP_NOT_YET)


class TestAssignmentOcc:
    def test_stale_order_version_on_assign_rejected(self, api):
        """PRD §2.7: "Order assignment requires the request body to carry
        `expected_order_version`, equal to the order's `version` as the dispatch
        manager last read it. A mismatch with the order's current `version` is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and no assignment is
        written."

        Design: Corner/cross_cutting/occ_stale_version_on_order_assign
        """
        ctx = setup_confirmed_order()
        vehicle = make_vehicle()
        driver = make_driver()
        stale_version = ctx["order"]["version"] - 1
        res = _assign_attempt(ctx["order"]["id"], vehicle["id"], driver["id"],
                              version=stale_version)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
