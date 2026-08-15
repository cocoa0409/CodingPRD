"""Route/store/product state machines, cross-entity route gates, and the
store-deactivation cascade (PRD §3.1, §3.2, §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_route,
    confirm_order,
    create_driver,
    create_order,
    create_product,
    create_route,
    create_store,
    create_trip,
    make_distributor_owner_headers,
    order_line,
    setup_planned_order,
    setup_route_with_store,
    upsert_par,
    validate_error,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]


def test_route_activate_requires_store_and_retire_lockdown(api):
    """PRD §3.1: "Activation from `DRAFT` additionally requires the route to
    have at least one `ACTIVE` store — a draft route with no live store is not
    ready and the request fails with `ERR_ROUTE_NOT_ACTIVE`."
    PRD §3.1: "Retirement moves an `ACTIVE` or `SUSPENDED` route to `RETIRED`
    — from any other state, `ERR_ROUTE_NOT_ACTIVE` — but only when no order on
    the route stands in `PLANNED` or `CONFIRMED` and no sale listing for the
    route stands in `DRAFT`, `LISTED`, `OFFER_PENDING`, or `UNDER_CONTRACT`;
    either blocker produces `ERR_ROUTE_HAS_OPEN_ORDERS`."
    PRD §3.1: "Retirement cascades: every `ACTIVE` store on the route becomes
    `INACTIVE`, and every `PLANNED` order on those stores becomes `CANCELLED`"

    Design: Corner/state_machines/route_activate_requires_store_and_retire_lockdown
    """
    refs = setup_route_with_store(prefix="AA", activate=False)
    d_id = refs["distributor"]["id"]
    r1 = refs["route"]["id"]
    s1 = refs["store"]["id"]
    # The store was onboarded while the route was DRAFT; remove its effect on
    # the first activation attempt by testing activation on a second,
    # genuinely store-less route, then return to the primary route.
    storeless = create_route(d_id, route_code="R-AA-EMPTY")

    err1 = api.activate_route(storeless["id"], TM)
    validate_error(err1, ApiErrorId.ERR_ROUTE_NOT_ACTIVE)

    route = validate_success(api.activate_route(r1, TM), 200)
    assert route["status"] == "ACTIVE"

    driver = create_driver(d_id, name="Al Driver")
    trip = create_trip(r1, driver["id"], d_id)
    product = create_product("LK-1", list_price_cents=250, shelf_life_days=30)
    order = create_order(
        s1, trip["id"], [order_line(product["id"], 1)], d_id,
        delivery_window_start="2026-08-10T08:00:00Z",
        delivery_window_end="2026-08-10T08:30:00Z",
    )

    err2 = api.retire_route(r1, TM)
    validate_error(err2, ApiErrorId.ERR_ROUTE_HAS_OPEN_ORDERS)

    api.cancel_order(order["id"], make_distributor_owner_headers(d_id))
    retired = validate_success(api.retire_route(r1, TM), 200)
    assert retired["status"] == "RETIRED"

    err3 = api.activate_route(r1, TM)
    validate_error(err3, ApiErrorId.ERR_ROUTE_NOT_ACTIVE)

    store = validate_success(api.get_store(s1, TM), 200)
    assert store["status"] == "INACTIVE", "retire cascade must deactivate the store"


def test_store_deactivate_blocked_by_confirmed_and_reactivate_gate(api):
    """PRD §3.1: "Deactivating a store moves it `ACTIVE` → `INACTIVE` and is
    refused from any other state with `ERR_STORE_NOT_ACTIVE`; it is also
    refused while any order for the store stands in `CONFIRMED`, with
    `ERR_STORE_HAS_CONFIRMED_ORDERS`."
    PRD §3.1: "Reactivating a store requires the store to be `INACTIVE` (else
    `ERR_STORE_NOT_ACTIVE`) and its route to be `ACTIVE` (else
    `ERR_ROUTE_NOT_ACTIVE`)."

    Design: Corner/state_machines/store_deactivate_blocked_by_confirmed_and_reactivate_gate
    """
    refs = setup_planned_order(prefix="AB", quantity_units=1)
    d_id = refs["distributor"]["id"]
    owner = make_distributor_owner_headers(d_id)
    confirm_order(refs["order"]["id"], d_id)

    err1 = api.deactivate_store(refs["store"]["id"], owner)
    validate_error(err1, ApiErrorId.ERR_STORE_HAS_CONFIRMED_ORDERS)

    api.cancel_order(refs["order"]["id"], owner)
    store = validate_success(api.deactivate_store(refs["store"]["id"], owner), 200)
    assert store["status"] == "INACTIVE"

    api.suspend_route(refs["route"]["id"], TM)
    err2 = api.reactivate_store(refs["store"]["id"], owner)
    validate_error(err2, ApiErrorId.ERR_ROUTE_NOT_ACTIVE)


def test_product_discontinue_terminal_and_order_gate(api):
    """PRD §3.1: "discontinuing moves it to `DISCONTINUED` (from any other
    state, `ERR_PRODUCT_DISCONTINUED`), after which it is silently excluded
    from future generated order lines and rejected outright in new manual
    order lines with `ERR_PRODUCT_DISCONTINUED` (HTTP 409)."

    Design: Corner/state_machines/product_discontinue_terminal_and_order_gate
    """
    refs = setup_planned_order(prefix="AM", quantity_units=1)
    d_id = refs["distributor"]["id"]
    p1 = refs["product"]["id"]

    validate_success(api.discontinue_product(p1, TM), 200)
    err1 = api.discontinue_product(p1, TM)
    validate_error(err1, ApiErrorId.ERR_PRODUCT_DISCONTINUED)

    err2 = api.create_order(
        {
            "store_id": refs["store"]["id"],
            "trip_id": refs["trip"]["id"],
            "lines": [{"product_id": p1, "quantity_units": 1}],
            "delivery_window_start": "2026-08-10T10:00:00Z",
            "delivery_window_end": "2026-08-10T10:30:00Z",
        },
        make_distributor_owner_headers(d_id),
    )
    validate_error(err2, ApiErrorId.ERR_PRODUCT_DISCONTINUED)


class TestOrderConfirmRequiresActiveRoute:
    def test_suspended_route_blocks_confirm_and_reactivation_restores(self, api):
        """PRD §3.1: "Suspending moves an `ACTIVE` route to `SUSPENDED` (any
        other starting state, `ERR_ROUTE_NOT_ACTIVE`), and a suspended route
        blocks both order confirmation and par-based order generation with
        `ERR_ROUTE_NOT_ACTIVE`."
        PRD §3.4: "The order must be `PLANNED` (else
        `ERR_ORDER_NOT_CONFIRMABLE`), its store `ACTIVE` (else
        `ERR_STORE_NOT_ACTIVE`), the store's route `ACTIVE` (else
        `ERR_ROUTE_NOT_ACTIVE`), and the trip still `PLANNED` (else
        `ERR_TRIP_NOT_PLANNED`)."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_active_route
        """
        refs = setup_planned_order(prefix="N", quantity_units=10)
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)

        api.suspend_route(refs["route"]["id"], TM)
        err = api.confirm_order(refs["order"]["id"], owner)
        validate_error(err, ApiErrorId.ERR_ROUTE_NOT_ACTIVE)

        api.activate_route(refs["route"]["id"], TM)
        order = validate_success(api.confirm_order(refs["order"]["id"], owner), 200)
        assert order["fulfillment_status"] == "CONFIRMED"

    def test_suspended_route_blocks_generate_orders(self, api):
        """PRD §3.2: "The trip's route must be `ACTIVE`, else
        `ERR_ROUTE_NOT_ACTIVE`, and the trip itself must be `PLANNED`, else
        `ERR_TRIP_NOT_PLANNED`."

        Design: Difficulty/cross_entity_state_dependency/order_confirm_requires_active_route
        """
        refs = setup_planned_order(prefix="N2", quantity_units=10)
        d_id = refs["distributor"]["id"]
        store = refs["store"]
        upsert_par(
            store["id"], d_id, refs["product"]["id"],
            store["version"], par_mon=10,
        )
        api.suspend_route(refs["route"]["id"], TM)
        err = api.generate_orders(refs["trip"]["id"], make_distributor_owner_headers(d_id))
        validate_error(err, ApiErrorId.ERR_ROUTE_NOT_ACTIVE)


def _setup_two_store_trip(api, prefix):
    """Two stores on one ACTIVE route; trip capacity 100; O_A PLANNED (20
    units) on the first store, O_B CONFIRMED (10 units) on the second."""
    refs = setup_route_with_store(prefix=prefix)
    d_id = refs["distributor"]["id"]
    store2 = create_store(refs["route"]["id"], d_id, store_code=f"S-{prefix}B")
    product = create_product(f"BUTTER-{prefix}", list_price_cents=250, shelf_life_days=60)
    driver = create_driver(d_id, name=f"Driver {prefix}")
    trip = create_trip(refs["route"]["id"], driver["id"], d_id, case_capacity=100)
    order_a = create_order(
        refs["store"]["id"], trip["id"], [order_line(product["id"], 20)], d_id,
        delivery_window_start="2026-08-10T08:00:00Z",
        delivery_window_end="2026-08-10T08:30:00Z",
    )
    order_b = create_order(
        store2["id"], trip["id"], [order_line(product["id"], 10)], d_id,
        delivery_window_start="2026-08-10T09:00:00Z",
        delivery_window_end="2026-08-10T09:30:00Z",
    )
    confirm_order(order_b["id"], d_id)
    refs.update({"store2": store2, "product": product, "driver": driver,
                 "trip": trip, "order_a": order_a, "order_b": order_b})
    return refs


class TestStoreDeactivationCascade:
    def test_deactivation_cancels_planned_orders_and_releases_cases(self, api):
        """PRD §3.1: "Deactivation cascades two levels deep: every `PLANNED`
        order for the store becomes `CANCELLED`, and each cancelled order
        releases its reserved cases, so the affected trips' `loaded_cases`
        recompute as the sum over remaining `CONFIRMED` orders."

        Design: Difficulty/transitive_cascade/store_deactivation_cascade_releases_trip_cases
        """
        refs = _setup_two_store_trip(api, "I")
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)

        trip_pre = validate_success(api.get_trip(refs["trip"]["id"], TM), 200)
        assert trip_pre["loaded_cases"] == 30

        store = validate_success(api.deactivate_store(refs["store"]["id"], owner), 200)
        assert store["status"] == "INACTIVE"

        order_a = validate_success(api.get_order(refs["order_a"]["id"], TM), 200)
        assert order_a["fulfillment_status"] == "CANCELLED"
        order_b = validate_success(api.get_order(refs["order_b"]["id"], TM), 200)
        assert order_b["fulfillment_status"] == "CONFIRMED", (
            "the other store's CONFIRMED order must be untouched"
        )
        trip_post = validate_success(api.get_trip(refs["trip"]["id"], TM), 200)
        assert trip_post["loaded_cases"] == 10, (
            "hop 3: trip reservation recomputed after release of the 20 cases"
        )

    def test_released_capacity_is_reusable_by_remaining_store(self, api):
        """PRD §3.4: "**Capacity re-validation** compares the trip's
        `loaded_cases` — which by then includes this order's reservation among
        all `PLANNED` and `CONFIRMED` reservations — against `case_capacity`,
        and rejects with `ERR_TRIP_CAPACITY_EXCEEDED` when the load would
        exceed capacity."
        PRD §3.1: "each cancelled order releases its reserved cases, so the
        affected trips' `loaded_cases` recompute as the sum over remaining
        `CONFIRMED` orders."

        Design: Difficulty/transitive_cascade/store_deactivation_cascade_releases_trip_cases
        """
        refs = _setup_two_store_trip(api, "I2")
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        api.deactivate_store(refs["store"]["id"], owner)

        # 10 (CONFIRMED) + 90 new == capacity 100: not exceeding, so it confirms.
        order_c = create_order(
            refs["store2"]["id"], refs["trip"]["id"],
            [order_line(refs["product"]["id"], 90)], d_id,
            delivery_window_start="2026-08-10T10:00:00Z",
            delivery_window_end="2026-08-10T10:30:00Z",
        )
        confirmed = validate_success(api.confirm_order(order_c["id"], owner), 200)
        assert confirmed["fulfillment_status"] == "CONFIRMED"
        trip = validate_success(api.get_trip(refs["trip"]["id"], TM), 200)
        assert trip["loaded_cases"] == 100
