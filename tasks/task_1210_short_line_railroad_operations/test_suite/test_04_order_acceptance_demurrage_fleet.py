"""Order acceptance gate ordering, demurrage boundary arithmetic, and the
fleet-conservation invariant across furnish and cancel (PRD §3.1, §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_railcar,
    make_customer_rep_headers,
    place_car_order,
    set_clock,
    setup_accepted_order,
    setup_customer_with_siding,
    setup_placed_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]


class TestAcceptanceGates:
    def test_siding_capacity_exceeded_on_accept(self, api, dispatcher_headers):
        """PRD §3.2: "Acceptance runs its own ordered gauntlet of business gates,
        and the order matters because a request failing several gates surfaces
        the earliest: first the delivery siding's `maintenance_agreement_status`
        must be `ACTIVE`, failing as `ERR_SIDING_AGREEMENT_INACTIVE`; then the
        order's `quantity` must not exceed the siding's `capacity_cars`, failing
        as `ERR_SIDING_CAPACITY_EXCEEDED`; and only then is the shipper's credit
        examined, a `credit_status` other than `GOOD` surfacing
        `ERR_CUSTOMER_CREDIT_SUSPENDED`."

        Design: Corner/validations/siding_capacity_exceeded_on_accept
        """
        ctx = setup_placed_order(quantity=9, car_type="BOX", capacity_cars=4)
        resp = api.accept_car_order(ctx["order"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_SIDING_CAPACITY_EXCEEDED)

    def test_credit_suspended_fiscal_error(self, api, dispatcher_headers):
        """PRD §3.2: "Acceptance runs its own ordered gauntlet of business gates,
        and the order matters because a request failing several gates surfaces
        the earliest: first the delivery siding's `maintenance_agreement_status`
        must be `ACTIVE`, failing as `ERR_SIDING_AGREEMENT_INACTIVE`; then the
        order's `quantity` must not exceed the siding's `capacity_cars`, failing
        as `ERR_SIDING_CAPACITY_EXCEEDED`; and only then is the shipper's credit
        examined, a `credit_status` other than `GOOD` surfacing
        `ERR_CUSTOMER_CREDIT_SUSPENDED`."

        Design: Corner/validations/credit_suspended_fiscal_error
        """
        ctx = setup_placed_order(quantity=2, car_type="BOX", capacity_cars=4)
        validate_success(api.update_customer(ctx["customer"]["id"], {"credit_status": "SUSPENDED"}, ADMIN))
        resp = api.accept_car_order(ctx["order"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_SUSPENDED)

    def test_accept_dual_failure_surfaces_siding_agreement_error(self, api, dispatcher_headers):
        """PRD §3.2: "Acceptance runs its own ordered gauntlet of business gates,
        and the order matters because a request failing several gates surfaces
        the earliest: first the delivery siding's `maintenance_agreement_status`
        must be `ACTIVE`, failing as `ERR_SIDING_AGREEMENT_INACTIVE`; then the
        order's `quantity` must not exceed the siding's `capacity_cars`, failing
        as `ERR_SIDING_CAPACITY_EXCEEDED`; and only then is the shipper's credit
        examined, a `credit_status` other than `GOOD` surfacing
        `ERR_CUSTOMER_CREDIT_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/accept_siding_safety_beats_credit_fiscal
        """
        ctx = setup_placed_order(quantity=2, car_type="BOX", capacity_cars=8)
        validate_success(api.suspend_siding(ctx["siding"]["id"], ADMIN))
        validate_success(api.update_customer(ctx["customer"]["id"], {"credit_status": "SUSPENDED"}, ADMIN))

        resp = api.accept_car_order(ctx["order"]["id"], dispatcher_headers)
        err = validate_error(resp, ApiErrorId.ERR_SIDING_AGREEMENT_INACTIVE)
        assert err["error_id"] == "ERR_SIDING_AGREEMENT_INACTIVE", (
            f"when the siding agreement and the customer credit both fail, the earlier "
            f"siding gate must surface, got {err['error_id']}"
        )

    def test_accept_credit_error_when_siding_gate_passes(self, api, dispatcher_headers):
        """PRD §3.2: "Acceptance runs its own ordered gauntlet of business gates,
        and the order matters because a request failing several gates surfaces
        the earliest: first the delivery siding's `maintenance_agreement_status`
        must be `ACTIVE`, failing as `ERR_SIDING_AGREEMENT_INACTIVE`; then the
        order's `quantity` must not exceed the siding's `capacity_cars`, failing
        as `ERR_SIDING_CAPACITY_EXCEEDED`; and only then is the shipper's credit
        examined, a `credit_status` other than `GOOD` surfacing
        `ERR_CUSTOMER_CREDIT_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/accept_siding_safety_beats_credit_fiscal
        """
        ctx = setup_placed_order(quantity=2, car_type="BOX", capacity_cars=8)
        validate_success(api.update_customer(ctx["customer"]["id"], {"credit_status": "SUSPENDED"}, ADMIN))
        resp = api.accept_car_order(ctx["order"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_SUSPENDED)


class TestDemurrageBoundary:
    def _setup_furnished_three_car_order(self, api):
        customer, segment, siding = setup_customer_with_siding(
            name="Valley Lumber", billing_email="ap@valleylumber.example", capacity_cars=6
        )
        for mark in ("GNWR 7001", "GNWR 7002", "GNWR 7003"):
            create_railcar(reporting_mark=mark, car_type="BOX")
        order = place_car_order(customer["id"], siding["id"], car_type="BOX", quantity=3,
                                needed_by_date="2026-05-10T00:00:00Z")
        validate_success(api.accept_car_order(order["id"], DISPATCH))
        furnished = validate_success(api.furnish_car_order(order["id"], {"count": 3}, DISPATCH))
        assert furnished["status"] == "FURNISHED"
        return customer, furnished

    def test_demurrage_free_allowance_bills_nothing(self, api, settlement_clerk_headers):
        """PRD §3.2: "The shipper's `demurrage_free_days` supplies the `free_days`
        allowance, and the billable days are the loading days minus the allowance,
        floored at zero — boundary-exact, so loading for exactly the free
        allowance bills nothing and only a strictly longer hold bills. The charge
        multiplies the billable days by `cars_held` — the order's current
        `cars_furnished_count` — at 7,500 cents, that is $75.00, per car per
        day."

        Design: Difficulty/boundary_precision_check/demurrage_free_day_boundary
        """
        customer, order = self._setup_furnished_three_car_order(api)
        set_clock("2026-05-03T00:00:00Z")  # exactly 2 loading days == the 2 free days
        read = validate_success(api.get_car_order_demurrage(order["id"], settlement_clerk_headers))
        assert read["free_days"] == 2, f"free_days must echo the customer allowance, got {read['free_days']}"
        assert read["billable_days"] == 0, (
            f"loading for exactly the free allowance bills nothing, got billable_days {read['billable_days']}"
        )
        assert read["charge_cents"] == 0, f"charge must be 0 at the boundary, got {read['charge_cents']}"

    def test_demurrage_one_day_beyond_allowance(self, api, settlement_clerk_headers):
        """PRD §3.2: "The shipper's `demurrage_free_days` supplies the `free_days`
        allowance, and the billable days are the loading days minus the allowance,
        floored at zero — boundary-exact, so loading for exactly the free
        allowance bills nothing and only a strictly longer hold bills. The charge
        multiplies the billable days by `cars_held` — the order's current
        `cars_furnished_count` — at 7,500 cents, that is $75.00, per car per
        day."

        Design: Difficulty/boundary_precision_check/demurrage_free_day_boundary
        """
        customer, order = self._setup_furnished_three_car_order(api)
        set_clock("2026-05-04T00:00:00Z")  # 3 loading days, one strictly beyond the allowance
        read = validate_success(api.get_car_order_demurrage(order["id"], settlement_clerk_headers))
        assert read["billable_days"] == 1, f"one day past the allowance must bill 1 day, got {read['billable_days']}"
        assert read["cars_held"] == 3, f"cars_held must be the furnished count 3, got {read['cars_held']}"
        assert read["charge_cents"] == 22500, (
            f"1 billable day * 3 cars * 7500 cents must total 22500, got {read['charge_cents']}"
        )


class TestFleetConservation:
    def test_furnish_assigns_cars_and_depletes_available(self, api, dispatcher_headers):
        """PRD §3.2: "Selection follows roster seniority — earliest `created_at`
        first, ties broken by ascending `reporting_mark` — and each selected car
        moves to `ASSIGNED` with its `assigned_order_id` pointing at the order,
        incrementing the car's `version` alongside the order's."

        Design: Difficulty/compensating_invariant/railcar_fleet_conservation
        """
        ctx = setup_accepted_order(quantity=2, car_type="BOX", capacity_cars=5, num_cars=3)
        order = validate_success(
            api.furnish_car_order(ctx["order"]["id"], {"count": 2}, dispatcher_headers)
        )
        assert order["cars_furnished_count"] == 2, (
            f"the forward furnish must assign 2 cars, got {order['cars_furnished_count']}"
        )
        cars, meta = validate_paginated(api.list_railcars(dispatcher_headers, params={"status": "AVAILABLE"}))
        assert meta["total_count"] == 1, (
            f"furnishing 2 of 3 cars must leave exactly 1 AVAILABLE, got {meta['total_count']}"
        )

    def test_cancel_restores_fleet_count(self, api, dispatcher_headers):
        """PRD §3.2: "Cancelling a `PARTIALLY_FURNISHED` or `FURNISHED` order
        returns each assigned car to `AVAILABLE` and clears its
        `assigned_order_id`; cancelling a `PLACED` or `ACCEPTED` order has no
        fleet to unwind."

        Design: Difficulty/compensating_invariant/railcar_fleet_conservation
        """
        ctx = setup_accepted_order(quantity=2, car_type="BOX", capacity_cars=5, num_cars=3)
        validate_success(api.furnish_car_order(ctx["order"]["id"], {"count": 2}, dispatcher_headers))

        cancelled = validate_success(
            api.cancel_car_order(ctx["order"]["id"], make_customer_rep_headers(ctx["customer"]["id"]))
        )
        assert cancelled["status"] == "CANCELLED", f"cancel must stand the order CANCELLED, got {cancelled['status']}"

        _cars, meta_avail = validate_paginated(api.list_railcars(dispatcher_headers, params={"status": "AVAILABLE"}))
        assert meta_avail["total_count"] == 3, (
            f"the compensating cancel must restore all cars to AVAILABLE, got {meta_avail['total_count']}"
        )
        _all, meta_all = validate_paginated(api.list_railcars(dispatcher_headers))
        assert meta_all["total_count"] == 3, (
            f"furnish + cancel must conserve the fleet count of 3, got {meta_all['total_count']}"
        )
