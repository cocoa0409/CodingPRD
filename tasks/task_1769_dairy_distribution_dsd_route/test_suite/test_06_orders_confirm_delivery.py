"""Order confirmation gates (dock buffer, capacity, credit), priority
conflicts, delivery guards, and immediate post-delivery consistency
(PRD §2.5, §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    cancel_order,
    confirm_order,
    create_order,
    create_store,
    create_trip,
    deliver_order,
    delivered_line,
    get_invoice_for_order,
    get_trip,
    make_distributor_owner_headers,
    make_driver_headers,
    order_line,
    patch_store,
    precool_and_depart,
    set_clock,
    setup_delivered_order,
    setup_planned_order,
    setup_route_with_store,
    create_driver,
    create_product,
    validate_error,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]


def test_order_state_errors_and_terminal_lockdown(api):
    """PRD §3.4: "The order must be `PLANNED` (else
    `ERR_ORDER_NOT_CONFIRMABLE`)"
    PRD §3.4: "An order may be cancelled by the owner from `PLANNED` or
    `CONFIRMED` — from any other state, `ERR_ORDER_NOT_CANCELLABLE`."
    PRD §3.4: "The order must be `CONFIRMED` (else
    `ERR_ORDER_NOT_DELIVERABLE`)"
    PRD §3.4: "Every delivered line's `scanned_code_date` must be on or after
    the order's `service_date`: delivering out-of-code product is refused with
    `ERR_OUT_OF_CODE_DELIVERY` (HTTP 422)."
    PRD §3.4: "an over-delivery, a missing line, or a duplicated line fails
    with `ERR_DELIVERY_QTY_EXCEEDS_ORDER` (HTTP 422)."

    Design: Corner/state_machines/order_state_errors_and_terminal_lockdown
    """
    refs = setup_route_with_store(prefix="AF", route_overrides={"service_weekdays": ["MON", "TUE"]})
    d_id = refs["distributor"]["id"]
    owner = make_distributor_owner_headers(d_id)
    product = create_product("LK-5", list_price_cents=250, shelf_life_days=30)
    driver = create_driver(d_id, name="Fi Driver")
    t1 = create_trip(refs["route"]["id"], driver["id"], d_id, service_date="2026-08-10")
    t2 = create_trip(refs["route"]["id"], driver["id"], d_id, service_date="2026-08-11")
    o1 = create_order(refs["store"]["id"], t1["id"], [order_line(product["id"], 1)], d_id,
                      delivery_window_start="2026-08-10T08:00:00Z",
                      delivery_window_end="2026-08-10T08:30:00Z")
    o2 = create_order(refs["store"]["id"], t1["id"], [order_line(product["id"], 2)], d_id,
                      delivery_window_start="2026-08-10T09:00:00Z",
                      delivery_window_end="2026-08-10T09:30:00Z")
    o3 = create_order(refs["store"]["id"], t2["id"], [order_line(product["id"], 3)], d_id,
                      delivery_window_start="2026-08-11T08:00:00Z",
                      delivery_window_end="2026-08-11T08:30:00Z")
    confirm_order(o1["id"], d_id)
    confirm_order(o2["id"], d_id)
    confirm_order(o3["id"], d_id)
    cancel_order(o2["id"], d_id)

    err1 = api.confirm_order(o1["id"], owner)
    validate_error(err1, ApiErrorId.ERR_ORDER_NOT_CONFIRMABLE)

    err2 = api.cancel_order(o2["id"], owner)
    validate_error(err2, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)

    precool_and_depart(t1["id"], driver["id"], "2026-08-10")

    err3 = api.deliver_order(
        o2["id"],
        {"delivered_lines": [delivered_line(product["id"], 2, "2026-09-01")]},
        make_driver_headers(driver["id"]),
    )
    validate_error(err3, ApiErrorId.ERR_ORDER_NOT_DELIVERABLE)

    err4 = api.deliver_order(
        o1["id"],
        {"delivered_lines": [delivered_line(product["id"], 1, "2026-08-05")]},
        make_driver_headers(driver["id"]),
    )
    validate_error(err4, ApiErrorId.ERR_OUT_OF_CODE_DELIVERY)

    err5 = api.deliver_order(
        o1["id"],
        {"delivered_lines": [delivered_line(product["id"], 5, "2026-09-01")]},
        make_driver_headers(driver["id"]),
    )
    validate_error(err5, ApiErrorId.ERR_DELIVERY_QTY_EXCEEDS_ORDER)

    o1_after = validate_success(api.get_order(o1["id"], TM), 200)
    assert o1_after["fulfillment_status"] == "CONFIRMED", (
        "failed deliveries must change nothing"
    )


class TestStoreDockBufferConflict:
    def _setup_confirmed_o1(self, api, prefix):
        refs = setup_planned_order(prefix=prefix, quantity_units=5)
        confirm_order(refs["order"]["id"], refs["distributor"]["id"])
        return refs

    def test_exactly_15_minutes_allowed_14_rejected(self, api):
        """PRD §3.4: "The **dock buffer** rule then rejects the confirmation
        with `ERR_DOCK_WINDOW_CONFLICT` when another order for the same store
        and service date in `CONFIRMED` or `DELIVERED` has a window whose
        start or end falls within 15 minutes of this window on either side."

        Design: Difficulty/resource_temporal_overlap/store_dock_buffer_conflict
        """
        refs = self._setup_confirmed_o1(api, "Q")
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        s1 = refs["store"]["id"]
        t1 = refs["trip"]["id"]
        pl = refs["product"]["id"]

        o2 = create_order(s1, t1, [order_line(pl, 5)], d_id,
                          delivery_window_start="2026-08-10T08:45:00Z",
                          delivery_window_end="2026-08-10T09:15:00Z")
        o3 = create_order(s1, t1, [order_line(pl, 5)], d_id,
                          delivery_window_start="2026-08-10T07:30:00Z",
                          delivery_window_end="2026-08-10T07:46:00Z")

        confirmed = validate_success(api.confirm_order(o2["id"], owner), 200)
        assert confirmed["fulfillment_status"] == "CONFIRMED", (
            "a gap of exactly 15 minutes equals the buffer and is allowed"
        )
        err = api.confirm_order(o3["id"], owner)
        validate_error(err, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)

    def test_buffer_scoped_to_same_store_and_service_date(self, api):
        """PRD §3.4: "The **dock buffer** rule then rejects the confirmation
        with `ERR_DOCK_WINDOW_CONFLICT` when another order for the same store
        and service date in `CONFIRMED` or `DELIVERED` has a window whose
        start or end falls within 15 minutes of this window on either side."

        Design: Difficulty/resource_temporal_overlap/store_dock_buffer_conflict
        """
        refs = self._setup_confirmed_o1(api, "Q2")
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        pl = refs["product"]["id"]
        store2 = create_store(refs["route"]["id"], d_id, store_code="S-Q2B")
        trip2 = create_trip(refs["route"]["id"], refs["driver"]["id"], d_id,
                            service_date="2026-08-11")

        # Same window, different store: no conflict.
        o2 = create_order(store2["id"], refs["trip"]["id"], [order_line(pl, 5)], d_id,
                          delivery_window_start="2026-08-10T08:00:00Z",
                          delivery_window_end="2026-08-10T08:30:00Z")
        ok1 = validate_success(api.confirm_order(o2["id"], owner), 200)
        assert ok1["fulfillment_status"] == "CONFIRMED"

        # Same store, different service date (5-minute time-of-day gap): allowed.
        o3 = create_order(refs["store"]["id"], trip2["id"], [order_line(pl, 5)], d_id,
                          delivery_window_start="2026-08-11T08:05:00Z",
                          delivery_window_end="2026-08-11T08:35:00Z")
        ok2 = validate_success(api.confirm_order(o3["id"], owner), 200)
        assert ok2["fulfillment_status"] == "CONFIRMED"


def test_credit_limit_equality_boundary(api):
    """PRD §3.4: "the **credit check** adds the store's `open_ar_cents` to the
    order's estimated subtotal at current prices and rejects with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402) only when the sum is strictly
    greater than `credit_limit_cents` — equality passes."

    Design: Corner/calculations/credit_limit_equality_boundary
    """
    refs = setup_route_with_store(prefix="BG", credit_limit_cents=2500)
    d_id = refs["distributor"]["id"]
    owner = make_distributor_owner_headers(d_id)
    store_b = create_store(refs["route"]["id"], d_id, store_code="S-BG-2",
                           credit_limit_cents=2499)
    product = create_product("CR-1", list_price_cents=250, shelf_life_days=30)
    driver = create_driver(d_id, name="Uma Driver")
    trip = create_trip(refs["route"]["id"], driver["id"], d_id)
    oa = create_order(refs["store"]["id"], trip["id"], [order_line(product["id"], 10)], d_id,
                      delivery_window_start="2026-08-10T08:00:00Z",
                      delivery_window_end="2026-08-10T08:30:00Z")
    ob = create_order(store_b["id"], trip["id"], [order_line(product["id"], 10)], d_id,
                      delivery_window_start="2026-08-10T09:00:00Z",
                      delivery_window_end="2026-08-10T09:30:00Z")

    confirmed = validate_success(api.confirm_order(oa["id"], owner), 200)
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        "2500 == 2500 passes; the rejection is strict-greater only"
    )
    err = api.confirm_order(ob["id"], owner)
    validate_error(err, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)


def test_capacity_exceeded_clean(api):
    """PRD §3.4: "**Capacity re-validation** compares the trip's
    `loaded_cases` — which by then includes this order's reservation among all
    `PLANNED` and `CONFIRMED` reservations — against `case_capacity`, and
    rejects with `ERR_TRIP_CAPACITY_EXCEEDED` when the load would exceed
    capacity."
    PRD §3.4: "the trip's `loaded_cases` immediately grows by the total cases
    — this is a reservation only, and capacity is enforced at confirmation,
    never at creation."

    Design: Corner/errors/capacity_exceeded_clean
    """
    refs = setup_planned_order(prefix="EC", quantity_units=20, case_capacity=50)
    d_id = refs["distributor"]["id"]
    owner = make_distributor_owner_headers(d_id)
    confirm_order(refs["order"]["id"], d_id)
    o2 = create_order(
        refs["store"]["id"], refs["trip"]["id"],
        [order_line(refs["product"]["id"], 40)], d_id,
        delivery_window_start="2026-08-10T10:30:00Z",
        delivery_window_end="2026-08-10T11:00:00Z",
    )
    err = api.confirm_order(o2["id"], owner)
    validate_error(err, ApiErrorId.ERR_TRIP_CAPACITY_EXCEEDED)
    trip = get_trip(refs["trip"]["id"])
    assert trip["loaded_cases"] == 60, (
        "the PLANNED reservation made at creation stands; confirm merely failed"
    )


class TestStateTrumpsFiscalOnConfirm:
    def test_cancelled_order_with_credit_breach_reports_state(self, api):
        """PRD §2.5: "the API applies a single global priority ladder, and a
        dual-failure request returns the error from the lowest priority
        number", with state-machine preconditions at rung (6) and fiscal
        limits at rung (11): "fiscal limits checked last
        (`ERR_CREDIT_LIMIT_EXCEEDED`, `ERR_PAYMENT_EXCEEDS_DUE`)".

        Design: Difficulty/priority_pair_validation_conflict/state_trumps_fiscal_on_confirm
        """
        refs = setup_planned_order(prefix="J", quantity_units=10, credit_limit_cents=1000)
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        cancel_order(refs["order"]["id"], d_id)

        err = api.confirm_order(refs["order"]["id"], owner)
        validate_error(err, ApiErrorId.ERR_ORDER_NOT_CONFIRMABLE)

    def test_suspended_route_with_credit_breach_reports_state(self, api):
        """PRD §2.5: "the API applies a single global priority ladder, and a
        dual-failure request returns the error from the lowest priority
        number" — the route-state failure (rung 6) precedes the fiscal check
        (rung 11).
        PRD §3.4: "the store's route `ACTIVE` (else `ERR_ROUTE_NOT_ACTIVE`)"

        Design: Difficulty/priority_pair_validation_conflict/state_trumps_fiscal_on_confirm
        """
        refs = setup_planned_order(prefix="J2", quantity_units=10, credit_limit_cents=1000)
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        api.suspend_route(refs["route"]["id"], TM)

        err = api.confirm_order(refs["order"]["id"], owner)
        validate_error(err, ApiErrorId.ERR_ROUTE_NOT_ACTIVE)


class TestTemporalTrumpsConstraintOnConfirm:
    def test_dock_conflict_with_capacity_breach_reports_temporal(self, api):
        """PRD §2.5: "the API applies a single global priority ladder, and a
        dual-failure request returns the error from the lowest priority
        number" — temporal interval rules at rung (8)
        (`ERR_DOCK_WINDOW_CONFLICT`, `ERR_TRIP_WINDOW_CONFLICT`,
        `ERR_READING_OUT_OF_ORDER`) precede capacity and structural
        constraints at rung (9).

        Design: Difficulty/priority_pair_validation_conflict/temporal_trumps_constraint_on_confirm
        """
        refs = setup_planned_order(prefix="K", quantity_units=20, case_capacity=50)
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        confirm_order(refs["order"]["id"], d_id)
        o2 = create_order(
            refs["store"]["id"], refs["trip"]["id"],
            [order_line(refs["product"]["id"], 40)], d_id,
            delivery_window_start="2026-08-10T08:35:00Z",
            delivery_window_end="2026-08-10T09:00:00Z",
        )
        err = api.confirm_order(o2["id"], owner)
        validate_error(err, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)

    def test_dock_conflict_with_credit_breach_reports_temporal(self, api):
        """PRD §2.5: "the API applies a single global priority ladder, and a
        dual-failure request returns the error from the lowest priority
        number" — temporal rung (8) precedes fiscal rung (11).

        Design: Difficulty/priority_pair_validation_conflict/temporal_trumps_constraint_on_confirm
        """
        refs = setup_planned_order(prefix="K2", quantity_units=10)
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        confirm_order(refs["order"]["id"], d_id)
        # Tighten the credit limit after the first confirm so O2 (estimated
        # 2500) breaches it while also sitting inside the dock buffer.
        store = validate_success(api.get_store(refs["store"]["id"], TM), 200)
        patch_store(store["id"], d_id, store["version"], credit_limit_cents=1000)
        o2 = create_order(
            refs["store"]["id"], refs["trip"]["id"],
            [order_line(refs["product"]["id"], 10)], d_id,
            delivery_window_start="2026-08-10T08:35:00Z",
            delivery_window_end="2026-08-10T09:00:00Z",
        )
        err = api.confirm_order(o2["id"], owner)
        validate_error(err, ApiErrorId.ERR_DOCK_WINDOW_CONFLICT)


def test_nonregulated_delivery_needs_no_pricing_period(api):
    """PRD §3.3: "The **regulated unit price** is computed at delivery time,
    per delivered line whose product is regulated, and snapshotted onto the
    line as `unit_price_cents`."
    PRD §3.3: "A non-regulated product's `unit_price_cents` is simply its
    `list_price_cents`."
    PRD §3.4: "its `pricing_basis` is `FINAL` when that period has an `ACTIVE`
    `FINAL` announcement at delivery and `PROVISIONAL` otherwise"

    Design: Corner/calculations/nonregulated_delivery_needs_no_pricing_period
    """
    refs = setup_delivered_order(prefix="BH", quantity_units=2)
    order = refs["order"]
    assert order["fulfillment_status"] == "DELIVERED"
    invoice = refs["invoice"]
    assert invoice["total_cents"] == 500
    assert invoice["pricing_basis"] == "PROVISIONAL"


def test_deliver_response_immediate_consistency(api):
    """PRD §3.4: "Second, a `CrateTransaction` of kind `DROP` is system-created
    for the delivered case count, increasing the store's `crate_balance` by
    that count and recomputing `deposit_liability_cents`. Third, the store's
    `open_ar_cents` — the sum of `amount_due_cents` over its `OPEN` invoices —
    is recomputed."
    PRD §3.4: "the order's `payment_status` moves to `INVOICED`"

    Design: Corner/endpoints/deliver_response_immediate_consistency
    """
    refs = setup_planned_order(
        prefix="DC", quantity_units=5,
        product_overrides={"units_per_case": 2, "list_price_cents": 250,
                           "shelf_life_days": 30},
        store_overrides={"crate_deposit_cents": 400},
    )
    d_id = refs["distributor"]["id"]
    confirm_order(refs["order"]["id"], d_id)
    precool_and_depart(refs["trip"]["id"], refs["driver"]["id"], "2026-08-10")
    set_clock("2026-08-10T09:00:00Z")
    delivered = deliver_order(
        refs["order"]["id"], refs["driver"]["id"],
        [delivered_line(refs["product"]["id"], 5, "2026-09-01")],
    )
    assert delivered["subtotal_cents"] == 1250, "5 x 250 in the same response"
    assert delivered["payment_status"] == "INVOICED"

    store = validate_success(api.get_store(refs["store"]["id"], TM), 200)
    assert store["crate_balance"] == 3, "ceil(5 / 2) = 3 cases dropped"
    assert store["deposit_liability_cents"] == 1200, "3 x 400"
    assert store["open_ar_cents"] == 1250, "no asynchronous lag"

    invoice = get_invoice_for_order(refs["order"]["id"])
    assert invoice["status"] == "OPEN"
    assert invoice["amount_due_cents"] == 1250
