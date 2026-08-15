"""Order lifecycle transitions, delivery routes, fulfillment RBAC."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    confirm_order,
    fulfill_order,
    get_product,
    get_route,
    make_customer,
    make_cylinder,
    make_order,
    make_product,
    make_route,
    make_staged_cash_order,
    pay_order,
    set_clock,
    stage_order,
    validate_error,
    validate_paginated,
    validate_success,
)

COUNTER_HEADERS = TEST_USERS["counter_rep_headers"]


class TestOrderTransitionGuards:
    def test_order_stage_from_draft_rejected(self, api, counter_rep_headers):
        """PRD §3.3: "Staging — the `CONFIRMED` → `STAGED` transition, again a
        `CounterRep` or `BranchManager` action — marks the order physically
        picked and ready." PRD §2.8: "The target entity's own state permits
        the requested transition — an order advancing along its fulfillment
        dimension, an enrollment advancing only from its initial state, a
        route dispatching only from its planned state, a returned cylinder
        accepted only from the correct holder, and so on. Violations are
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/order_stage_from_draft_rejected
        """
        customer = make_customer(account_no="ACC-SM2", name="Skip Co",
                                 terms="CASH")
        product = make_product(sku="HG-SM2", name="Pliers",
                               category="HARDGOOD", retail_price_cents=1500,
                               stock=1)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        resp = api.stage_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_order_cancel_after_fulfill_rejected(self, api,
                                                 counter_rep_headers):
        """PRD §3.4: "Either way the order lands in the terminal `CANCELLED`
        state with its `version` incremented; `FULFILLED` is the other
        terminal state, and neither terminal state can be cancelled out of."

        Design: Corner/state_machines/order_cancel_after_fulfill_rejected_terminal_lockdown
        """
        customer = make_customer(account_no="ACC-SM3", name="Lock Co",
                                 terms="CASH")
        product = make_product(sku="HG-SM3", name="Goggles",
                               category="HARDGOOD", retail_price_cents=3000,
                               stock=1)
        order = make_staged_cash_order(customer["id"], product["id"], 1)
        fulfilled = fulfill_order(order["id"])
        assert fulfilled["fulfillment_status"] == "FULFILLED"
        resp = api.cancel_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_order_cancel_restores_stock_and_route_units(self, api):
        """PRD §3.4: "Cancelling a confirmed or staged order restores each
        hardgood line's quantity to its product's `stock_on_hand` and, for a
        route order, subtracts the order's `units` from the route's
        `reserved_units`." PRD §3.5: "From then on `reserved_units` is a
        derived figure: the sum of `units` over the orders bound to the route
        whose `fulfillment_status` is `CONFIRMED` or `STAGED`."

        Design: Corner/state_machines/order_cancel_restores_stock_and_route_units
        """
        customer = make_customer(account_no="ACC-SM4", name="Undo Co",
                                 terms="CASH")
        product = make_product(sku="HG-SM4", name="Apron", category="HARDGOOD",
                               retail_price_cents=4000, stock=5)
        route = make_route(route_date="2026-08-03", truck_capacity_units=5)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 2}],
                           fulfillment="ROUTE", route_id=route["id"])
        confirm_order(order["id"])
        assert get_route(route["id"])["reserved_units"] == 2, \
            "confirm reserved the units"
        validate_success(api.cancel_order(order["id"], COUNTER_HEADERS))
        assert get_route(route["id"])["reserved_units"] == 0, \
            "cancel released the route units"
        assert get_product(product["id"])["stock_on_hand"] == 5, \
            "cancel restored the hardgood stock (5 -> 3 -> 5)"


class TestPaymentGuards:
    def test_cash_fulfill_requires_prior_payment(self, api,
                                                 counter_rep_headers):
        """PRD §3.4: "A route order can fulfill only after its route has been
        dispatched (`ERR_ROUTE_NOT_DISPATCHED`), and a cash customer's order
        can fulfill only once its `payment_status` is `PAID`
        (`ERR_PAYMENT_REQUIRED`)."

        Design: Corner/validations/cash_fulfill_requires_prior_payment
        """
        customer = make_customer(account_no="ACC-VA4", name="Unpaid Co",
                                 terms="CASH")
        product = make_product(sku="HG-VA4", name="Cap", category="HARDGOOD",
                               retail_price_cents=1200, stock=1)
        order = make_staged_cash_order(customer["id"], product["id"], 1,
                                       pay=False)
        assert order["payment_status"] == "UNPAID"
        resp = api.fulfill_order(order["id"], {}, counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_REQUIRED)

    def test_pay_amount_mismatch_rejected(self, api, counter_rep_headers):
        """PRD §3.4: "The supplied `amount_cents` must equal the order's
        `total_cents` exactly; an over- or under-payment is rejected with
        `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/validations/pay_amount_mismatch_rejected
        """
        customer = make_customer(account_no="ACC-VA5", name="Exact Co",
                                 terms="CASH")
        product = make_product(sku="HG-VA5", name="Shade 10 Lens",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=1)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}])
        confirmed = confirm_order(order["id"])
        assert confirmed["total_cents"] == 10000
        resp = api.pay_order(order["id"], {"amount_cents": 9999},
                             counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)


class TestRouteCapacityAndGates:
    def test_route_capacity_equality_then_overflow(self, api,
                                                   counter_rep_headers):
        """PRD §3.3: "A route order may confirm only onto a route that is
        still `PLANNED` (`ERR_ROUTE_NOT_ACCEPTING`), and only while the truck
        has room: the route's `reserved_units` plus the order's `units` may
        not exceed the route's `truck_capacity_units` — landing exactly at
        capacity is allowed, one unit over is `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Corner/calculations/route_capacity_equality_then_overflow
        """
        customer = make_customer(account_no="ACC-CA6", name="Truck Co",
                                 terms="CASH")
        product = make_product(sku="HG-CA6", name="Gloves",
                               category="HARDGOOD", retail_price_cents=1000,
                               stock=10)
        route = make_route(route_date="2026-08-06", truck_capacity_units=4)
        for qty in (2, 2):
            order = make_order(customer["id"],
                               [{"product_id": product["id"], "qty": qty}],
                               fulfillment="ROUTE", route_id=route["id"])
            confirmed = confirm_order(order["id"])
            assert confirmed["fulfillment_status"] == "CONFIRMED"
        overflow = make_order(customer["id"],
                              [{"product_id": product["id"], "qty": 1}],
                              fulfillment="ROUTE", route_id=route["id"])
        resp = api.confirm_order(overflow["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        assert get_route(route["id"])["reserved_units"] == 4, \
            "2 + 2 == capacity: equality allowed; 4 + 1 > 4 rejected"

    def test_route_not_accepting_after_dispatch(self, api, counter_rep_headers,
                                                route_driver_headers):
        """PRD §3.3: "A route order may confirm only onto a route that is
        still `PLANNED` (`ERR_ROUTE_NOT_ACCEPTING`)".

        Design: Corner/validations/route_not_accepting_after_dispatch
        """
        customer = make_customer(account_no="ACC-VA13", name="Late Co",
                                 terms="CASH")
        product = make_product(sku="HG-VA13", name="Hose", category="HARDGOOD",
                               retail_price_cents=1500, stock=5)
        route = make_route(route_date="2026-08-07", truck_capacity_units=5)
        validate_success(api.dispatch_route(route["id"], route_driver_headers))
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}],
                           fulfillment="ROUTE", route_id=route["id"])
        resp = api.confirm_order(order["id"], counter_rep_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_ACCEPTING)

    def test_route_close_blocked_with_open_orders(self, api,
                                                  route_driver_headers):
        """PRD §3.5: "Closing — `DISPATCHED` → `CLOSED`, same roles — ends the
        day, and is refused with `ERR_ROUTE_HAS_OPEN_ORDERS` while any bound
        order is still in a non-terminal state: every order on the route must
        be `FULFILLED` or `CANCELLED` before the route can close."

        Design: Corner/state_machines/route_close_blocked_with_open_orders
        """
        customer = make_customer(account_no="ACC-SM10", name="Open Co",
                                 terms="CASH")
        product = make_product(sku="HG-SM10", name="Wire 10lb",
                               category="HARDGOOD", retail_price_cents=6000,
                               stock=1)
        route = make_route(route_date="2026-08-04", truck_capacity_units=3)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}],
                           fulfillment="ROUTE", route_id=route["id"])
        confirmed = confirm_order(order["id"])
        pay_order(order["id"], confirmed["total_cents"])
        stage_order(order["id"])
        validate_success(api.dispatch_route(route["id"], route_driver_headers))
        resp = api.close_route(route["id"], route_driver_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_OPEN_ORDERS)


class TestFulfillRouteDispatchGate:
    def _staged_paid_route_order(self):
        customer = make_customer(account_no="ACC-XD2", name="Route Co",
                                 terms="CASH")
        product = make_product(sku="HG-XD2", name="Tip Cleaner",
                               category="HARDGOOD", retail_price_cents=10000,
                               stock=5)
        route = make_route(route_date="2026-08-02", truck_capacity_units=10)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}],
                           fulfillment="ROUTE", route_id=route["id"])
        confirmed = confirm_order(order["id"])
        pay_order(order["id"], confirmed["total_cents"])
        stage_order(order["id"])
        return customer, product, route, confirmed

    def test_fulfill_blocked_until_route_dispatched(self, api,
                                                    route_driver_headers):
        """PRD §3.4: "A route order can fulfill only after its route has been
        dispatched (`ERR_ROUTE_NOT_DISPATCHED`)". PRD §3.3: the 10000-cent
        subtotal "is strictly below the free-delivery threshold of 20000
        cents", so the flat 2500-cent delivery fee applies and the confirmed
        total is 12500.

        Design: Difficulty/cross_entity_state_dependency/route_order_fulfill_blocked_until_route_dispatched
        """
        _customer, _product, route, confirmed = self._staged_paid_route_order()
        assert confirmed["total_cents"] == 12500, "10000 + 2500 delivery fee"
        resp = api.fulfill_order(confirmed["id"], {}, route_driver_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED)

    def test_fulfill_succeeds_after_dispatch(self, api, route_driver_headers):
        """PRD §3.4: "A route order can fulfill only after its route has been
        dispatched (`ERR_ROUTE_NOT_DISPATCHED`)" — and "Dispatching —
        `PLANNED` → `DISPATCHED`, performed by a `RouteDriver` or
        `BranchManager` — sends the truck out, and only after dispatch may the
        route's orders be fulfilled by the driver" (§3.5).

        Design: Difficulty/cross_entity_state_dependency/route_order_fulfill_blocked_until_route_dispatched
        """
        _customer, _product, route, confirmed = self._staged_paid_route_order()
        validate_success(api.dispatch_route(route["id"], route_driver_headers))
        fulfilled = validate_success(api.fulfill_order(confirmed["id"], {},
                                                       route_driver_headers))
        assert fulfilled["fulfillment_status"] == "FULFILLED"


class TestFulfillmentRoleSplit:
    def test_driver_cannot_fulfill_will_call_order(self, api,
                                                   route_driver_headers):
        """PRD §3.4: "the acting role depends on how the order ships: a
        `CounterRep` fulfills will-call orders, a `RouteDriver` fulfills route
        orders at the stop, and a `BranchManager` may fulfill either; any
        other combination is `ERR_FORBIDDEN`."

        Design: Corner/rbac/driver_cannot_fulfill_will_call_order
        """
        customer = make_customer(account_no="ACC-RB1", name="Counter Co",
                                 terms="CASH")
        product = make_product(sku="HG-RB1", name="Marker",
                               category="HARDGOOD", retail_price_cents=900,
                               stock=1)
        order = make_staged_cash_order(customer["id"], product["id"], 1)
        resp = api.fulfill_order(order["id"], {}, route_driver_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_branch_manager_fulfills_route_order_override(
            self, api, branch_manager_headers, route_driver_headers):
        """PRD §3.4: "the acting role depends on how the order ships: a
        `CounterRep` fulfills will-call orders, a `RouteDriver` fulfills route
        orders at the stop, and a `BranchManager` may fulfill either; any
        other combination is `ERR_FORBIDDEN`."

        Design: Corner/rbac/branch_manager_fulfills_route_order_override
        """
        customer = make_customer(account_no="ACC-RB5", name="Mgr Co",
                                 terms="CASH")
        product = make_product(sku="HG-RB5", name="Stand", category="HARDGOOD",
                               retail_price_cents=7000, stock=1)
        route = make_route(route_date="2026-08-08", truck_capacity_units=4)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}],
                           fulfillment="ROUTE", route_id=route["id"])
        confirmed = confirm_order(order["id"])
        assert confirmed["total_cents"] == 9500, "7000 + 2500 delivery fee"
        pay_order(order["id"], confirmed["total_cents"])
        stage_order(order["id"])
        validate_success(api.dispatch_route(route["id"], route_driver_headers))
        fulfilled = validate_success(api.fulfill_order(order["id"], {},
                                                       branch_manager_headers))
        assert fulfilled["fulfillment_status"] == "FULFILLED"


class TestSpecialMixStagingWindow:
    def test_mix_stage_before_available_date_then_allowed(
            self, api, counter_rep_headers):
        """PRD §3.3: "Two derived figures appear immediately: `units`, the sum
        of quantities across all lines, and `available_date`, which for orders
        containing specialty-gas lines is the order's creation date plus the
        largest `lead_time_days` among those specialty lines, and which is
        null for orders without specialty lines." and "An order containing
        specialty-gas lines may stage only once the logical clock date is on
        or after its `available_date`; an earlier attempt is rejected with
        `ERR_MIX_NOT_READY`."

        Design: Corner/validations/mix_stage_before_available_date_rejected_then_allowed
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(account_no="ACC-VA15", name="Mix Gas Co",
                                 terms="CASH")
        make_cylinder(serial_no="CYL-VA15", gas_grade="AR_CO2_7525",
                      size="LARGE")
        product = make_product(sku="SG-VA15", name="75/25 Mix",
                               category="SPECIALTY_GAS",
                               gas_grade="AR_CO2_7525", retail_price_cents=8000,
                               lead_time_days=5)
        order = make_order(customer["id"],
                           [{"product_id": product["id"], "qty": 1}],
                           order_type="SPECIAL_MIX")
        assert order["available_date"] == "2026-08-06", \
            "created 2026-08-01 + 5 lead days"
        confirm_order(order["id"])
        set_clock("2026-08-03T00:00:00Z")
        early = api.stage_order(order["id"], counter_rep_headers)
        validate_error(early, ApiErrorId.ERR_MIX_NOT_READY)
        set_clock("2026-08-06T00:00:00Z")
        staged = validate_success(api.stage_order(order["id"],
                                                  counter_rep_headers))
        assert staged["fulfillment_status"] == "STAGED", \
            "staging on the available_date itself passes (inclusive boundary)"


class TestOrderListing:
    def test_orders_filtered_by_customer(self, api, counter_rep_headers):
        """PRD §3.3: "The order list accepts `customer_id`, `route_id`,
        `invoice_id`, and `fulfillment_status` filters."

        Design: Corner/endpoints/orders_filtered_by_customer_returns_only_their_orders
        """
        cust_a = make_customer(account_no="ACC-EP4", name="A Co", terms="CASH")
        cust_b = make_customer(account_no="ACC-EP5", name="B Co", terms="CASH")
        product = make_product(sku="HG-EP1", name="Crate", category="HARDGOOD",
                               retail_price_cents=100, stock=4)
        order_a = make_order(cust_a["id"],
                             [{"product_id": product["id"], "qty": 1}])
        make_order(cust_b["id"], [{"product_id": product["id"], "qty": 1}])
        data, meta = validate_paginated(api.list_orders(
            counter_rep_headers, params={"customer_id": cust_a["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == order_a["id"]
