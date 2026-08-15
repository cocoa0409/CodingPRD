"""Order pipeline: parallel fulfillment/billing axes, credit gates, factory
sourcing cutoff and lead times, invoicing gate."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_product, create_branch, create_customer, create_branch_stock,
    create_order, create_order_with_line, create_confirmed_order_with_line,
    create_shipped_line, reserve_line, allocate_line, set_clock,
    get_order, get_order_line, get_customer,
    assert_order, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_allocated_order():
    """Product 10000; stock 10; confirmed order line qty 1, reserved, allocated."""
    product = create_product(sku="GRX-075", list_price_cents=10000, family="GEARBOX")
    branch = create_branch(code="NYC-05")
    customer = create_customer(name="Hudson Plant")
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=10)
    order, line = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    reserve_line(line["id"], stock["id"], 1)
    line = allocate_line(line["id"])
    return {"product": product, "branch": branch, "customer": customer,
            "stock": stock, "order": order, "line": line}


def test_ship_and_invoice_move_only_their_own_axis(api):
    """PRD §3.4: "**The billing axis** evolves independently of fulfillment;
    neither axis's mutation alters the other."
    PRD §3.4: "A `BranchManager` invoices an order whose `fulfillment_status`
    is `SHIPPED` (`ERR_ORDER_NOT_FULLY_SHIPPED`, 409) and whose billing is
    `UNBILLED` (`ERR_ORDER_ALREADY_INVOICED`, 409); billing moves to `INVOICED`
    and the customer's `open_receivables_cents` grows by `total_cents`."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_fulfillment_and_billing_axes
    """
    ctx = _setup_allocated_order()
    line = get_success_data(api.ship_line(ctx["line"]["id"], MANAGER))
    assert line["sourcing_status"] == "SHIPPED"
    order = get_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "SHIPPED"
    assert order["billing_status"] == "UNBILLED", (
        "ship must not advance billing")

    invoiced = validate_success(api.invoice_order(order["id"], MANAGER), 200)
    assert invoiced["billing_status"] == "INVOICED"
    assert invoiced["fulfillment_status"] == "SHIPPED", (
        "invoice must not move fulfillment")


def test_partial_then_full_payment_and_close_gate(api):
    """PRD §3.4: "`paid_cents` accumulates, billing moves to `PARTIALLY_PAID`
    while some balance remains and to `PAID` when `paid_cents` equals
    `total_cents`, and `open_receivables_cents` recomputes."
    PRD §3.4: "a `BranchManager` closes an order that is `SHIPPED`
    (`ERR_ORDER_NOT_FULLY_SHIPPED`) and `PAID` (`ERR_ORDER_NOT_PAID`, 409),
    moving fulfillment to `CLOSED`."

    Design: Difficulty/non_linear_state_machine/sales_order_parallel_fulfillment_and_billing_axes
    """
    ctx = _setup_allocated_order()
    get_success_data(api.ship_line(ctx["line"]["id"], MANAGER))
    validate_success(api.invoice_order(ctx["order"]["id"], MANAGER), 200)

    paid1 = validate_success(api.record_payment(
        ctx["order"]["id"], {"amount_cents": 4000}, MANAGER), 200)
    assert paid1["billing_status"] == "PARTIALLY_PAID"
    assert paid1["paid_cents"] == 4000
    assert paid1["fulfillment_status"] == "SHIPPED"

    paid2 = validate_success(api.record_payment(
        ctx["order"]["id"], {"amount_cents": 6000}, MANAGER), 200)
    assert paid2["billing_status"] == "PAID"
    assert paid2["paid_cents"] == 10000
    customer = get_customer(ctx["customer"]["id"])
    assert customer["open_receivables_cents"] == 0

    closed = validate_success(api.close_order(ctx["order"]["id"], MANAGER), 200)
    assert closed["fulfillment_status"] == "CLOSED"


def test_order_confirm_blocked_by_customer_credit_hold(api):
    """PRD §3.4: "the customer's `credit_status` must be `GOOD`
    (`ERR_CUSTOMER_CREDIT_HOLD`, 402)".

    Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_customer_credit_hold
    """
    product = create_product(sku="MTR-5HP", list_price_cents=10000)
    branch = create_branch(code="MIA-13")
    customer = create_customer(name="Sunshine Plant")
    validate_success(api.patch_customer(
        customer["id"], {"credit_status": "HOLD"}, CONTRACT_ADMIN), 200)
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    res = api.confirm_order(order["id"], REP)
    validate_error(res, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD, expected_status=402)
    order_after = get_order(order["id"])
    assert order_after["fulfillment_status"] == "DRAFT", (
        "credit hold must leave the order DRAFT")


def test_confirm_unblocked_after_credit_hold_released(api):
    """PRD §3.4: "the customer's `credit_status` must be `GOOD`
    (`ERR_CUSTOMER_CREDIT_HOLD`, 402), and the customer's
    `open_receivables_cents` plus the order's freshly computed `total_cents`
    must not exceed `credit_limit_cents` (`ERR_CREDIT_LIMIT_EXCEEDED`, 402)."

    Design: Difficulty/cross_entity_state_dependency/order_confirm_blocked_by_customer_credit_hold
    """
    product = create_product(sku="MTR-5HP", list_price_cents=10000)
    branch = create_branch(code="MIA-13")
    customer = create_customer(name="Sunshine Plant")
    validate_success(api.patch_customer(
        customer["id"], {"credit_status": "HOLD"}, CONTRACT_ADMIN), 200)
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    validate_error(api.confirm_order(order["id"], REP),
                   ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD, expected_status=402)
    validate_success(api.patch_customer(
        customer["id"], {"credit_status": "GOOD"}, CONTRACT_ADMIN), 200)
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    assert confirmed["fulfillment_status"] == "CONFIRMED"
    assert confirmed["total_cents"] == 10000


def test_order_created_with_parallel_initial_states(api):
    """PRD §3.4: "The order is born on two independent axes:
    `fulfillment_status` `DRAFT` and `billing_status` `UNBILLED`, with
    `subtotal_cents`, `expedite_fees_cents`, `total_cents`, and `paid_cents`
    all zero and `priced_at` null."
    PRD §3.4: "optionally a `price_variant` — `ORDER_DATE` (the default) or
    `SHIP_DATE`."

    Design: Corner/state_machines/order_created_with_parallel_initial_states
    """
    branch = create_branch(code="INI-01")
    customer = create_customer(name="Init Plant", credit_limit_cents=1000000)
    order = validate_success(api.create_order(
        {"customer_id": customer["id"], "branch_id": branch["id"]}, REP), 201)
    assert_order(order)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["billing_status"] == "UNBILLED"
    assert order["total_cents"] == 0
    assert order["priced_at"] is None
    assert order["price_variant"] == "ORDER_DATE"


def test_ship_line_from_pending_sourcing_rejected(api):
    """PRD §3.4: "Shipping, again a `BranchManager` action, requires
    `ALLOCATED` (`ERR_LINE_NOT_SHIPPABLE`, 409)".

    Design: Corner/state_machines/ship_line_from_pending_sourcing_rejected
    """
    product = create_product(sku="BRG-6011", list_price_cents=1000)
    branch = create_branch(code="INV-02")
    customer = create_customer(name="Inv Plant", credit_limit_cents=1000000)
    order, line = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    res = api.ship_line(line["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_LINE_NOT_SHIPPABLE, expected_status=409)
    assert get_order_line(line["id"])["sourcing_status"] == "PENDING_SOURCING"
    assert get_order(order["id"])["fulfillment_status"] == "CONFIRMED"


def test_cancelled_order_is_terminal(api):
    """PRD §3.4: "**Cancellation** is available to a `CounterSalesRep` only
    while the order is pre-shipment: `fulfillment_status` must be `DRAFT`,
    `CONFIRMED`, or `FULLY_SOURCED` and no line may be `SHIPPED`
    (`ERR_ORDER_NOT_CANCELLABLE`, 409)" and "`CLOSED` and `CANCELLED` are
    terminal."

    Design: Corner/state_machines/cancelled_order_is_terminal
    """
    product = create_product(sku="BRG-6012", list_price_cents=1000)
    branch = create_branch(code="TRM-03")
    customer = create_customer(name="Term Plant", credit_limit_cents=1000000)
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1)
    cancelled = validate_success(api.cancel_order(order["id"], REP), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    res = api.cancel_order(order["id"], REP)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE, expected_status=409)
    assert get_order(order["id"])["fulfillment_status"] == "CANCELLED"


def test_invoice_requires_fully_shipped_order(api):
    """PRD §3.4: "A `BranchManager` invoices an order whose
    `fulfillment_status` is `SHIPPED` (`ERR_ORDER_NOT_FULLY_SHIPPED`, 409) and
    whose billing is `UNBILLED` (`ERR_ORDER_ALREADY_INVOICED`, 409); billing
    moves to `INVOICED` and the customer's `open_receivables_cents` grows by
    `total_cents`."

    Design: Corner/endpoints/invoice_requires_fully_shipped_order
    """
    product = create_product(sku="BRG-6039", list_price_cents=1000)
    branch = create_branch(code="INV-26")
    customer = create_customer(name="Invoice Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=5)
    order = create_order(customer["id"], branch["id"])
    l1 = get_success_data(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1}, REP))
    l2 = get_success_data(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1}, REP))
    validate_success(api.confirm_order(order["id"], REP), 200)
    reserve_line(l1["id"], stock["id"], 1)
    reserve_line(l2["id"], stock["id"], 1)
    allocate_line(l1["id"])
    allocate_line(l2["id"])
    get_success_data(api.ship_line(l1["id"], MANAGER))
    order_mid = get_order(order["id"])
    assert order_mid["fulfillment_status"] == "PARTIALLY_SHIPPED"
    res = api.invoice_order(order["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_FULLY_SHIPPED, expected_status=409)

    get_success_data(api.ship_line(l2["id"], MANAGER))
    invoiced = validate_success(api.invoice_order(order["id"], MANAGER), 200)
    assert invoiced["billing_status"] == "INVOICED"
    assert get_customer(customer["id"])["open_receivables_cents"] == 2000


def test_credit_limit_exceeded_boundary_equality(api):
    """PRD §3.4: "the customer's `open_receivables_cents` plus the order's
    freshly computed `total_cents` must not exceed `credit_limit_cents`
    (`ERR_CREDIT_LIMIT_EXCEEDED`, 402)".

    Design: Corner/errors/credit_limit_exceeded_boundary_equality
    """
    product = create_product(sku="BRG-6041", list_price_cents=10000)
    branch = create_branch(code="CRD-28")
    customer_a = create_customer(name="Limit Exact Plant", credit_limit_cents=10000)
    customer_b = create_customer(name="Limit Short Plant", credit_limit_cents=9999)
    order_a, _ = create_order_with_line(
        customer_a["id"], branch["id"], product["id"], qty=1)
    order_b, _ = create_order_with_line(
        customer_b["id"], branch["id"], product["id"], qty=1)
    confirmed = validate_success(api.confirm_order(order_a["id"], REP), 200)
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        "total exactly equal to the credit limit must pass (<= semantics)")
    res = api.confirm_order(order_b["id"], REP)
    validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, expected_status=402)
    assert get_order(order_b["id"])["fulfillment_status"] == "DRAFT"


def test_factory_cutoff_boundary_at_exact_cutoff_hour(api):
    """PRD §3.4: "if the tier is `NONE` or `STANDARD` and the branch-local hour
    is at or past `expedite_cutoff_hour`, the placement is rejected with
    `ERR_FACTORY_ORDER_CUTOFF_PASSED` (409) — `RUSH` and `EMERGENCY` lines are
    exempt from the cutoff."

    Design: Corner/validations/factory_cutoff_boundary_at_exact_cutoff_hour
    """
    set_clock("2026-08-03T09:00:00Z")
    product = create_product(sku="BRG-6035", list_price_cents=1000)
    branch = create_branch(code="CUT-23")
    customer = create_customer(name="Cutoff Plant", credit_limit_cents=1000000)
    order = create_order(customer["id"], branch["id"])
    l1 = get_success_data(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1}, REP))
    l2 = get_success_data(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1}, REP))
    validate_success(api.confirm_order(order["id"], REP), 200)

    set_clock("2026-08-03T13:59:00Z")  # 13:59 < 14 cutoff
    placed = validate_success(api.place_factory_order(l1["id"], REP), 200)
    assert placed["sourcing_status"] == "FACTORY_ORDERED"

    set_clock("2026-08-03T14:00:00Z")  # exactly the cutoff hour: >= semantics
    res = api.place_factory_order(l2["id"], REP)
    validate_error(res, ApiErrorId.ERR_FACTORY_ORDER_CUTOFF_PASSED, expected_status=409)


def test_factory_receipt_respects_tier_adjusted_lead_time(api):
    """PRD §3.4: "A `BranchManager` later receives factory goods, which requires
    the line be `FACTORY_ORDERED` (`ERR_LINE_NOT_FACTORY_ORDERED`, 409) and
    requires that now be at least `factory_ordered_at` plus the effective lead
    time — the stock record's `factory_lead_time_days`, halved with a floor of
    1 day for `RUSH`, and 0 days for `EMERGENCY`
    (`ERR_FACTORY_LEAD_TIME_UNMET`, 409). Receipt lands the goods on the shelf
    first: the branch-and-product stock record's `on_hand_qty` grows by the
    line `qty`, and the order's fulfillment re-evaluates."

    Design: Corner/validations/factory_receipt_respects_tier_adjusted_lead_time
    """
    set_clock("2026-08-03T09:00:00Z")
    product = create_product(sku="BRG-6036", list_price_cents=1000)
    branch = create_branch(code="LEAD-24")
    customer = create_customer(name="Lead Plant", credit_limit_cents=1000000)
    stock = create_branch_stock(
        branch["id"], product["id"], on_hand_qty=0, factory_lead_time_days=4)
    order = create_order(customer["id"], branch["id"])
    l1 = get_success_data(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1,
                      "expedite_tier": "EMERGENCY"}, REP))
    l2 = get_success_data(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1,
                      "expedite_tier": "RUSH"}, REP))
    l3 = get_success_data(api.add_order_line(
        order["id"], {"product_id": product["id"], "qty": 1}, REP))
    validate_success(api.confirm_order(order["id"], REP), 200)
    for line in (l1, l2, l3):
        validate_success(api.place_factory_order(line["id"], REP), 200)

    # EMERGENCY: effective lead 0 days — same-instant receipt succeeds.
    received1 = validate_success(api.receive_factory(l1["id"], MANAGER), 200)
    assert received1["sourcing_status"] == "FACTORY_RECEIVED"

    set_clock("2026-08-05T09:00:00Z")  # +2 days
    # RUSH: 4 halved = 2 days — receipt at +2d succeeds.
    received2 = validate_success(api.receive_factory(l2["id"], MANAGER), 200)
    assert received2["sourcing_status"] == "FACTORY_RECEIVED"
    # NONE: needs the full 4 days — +2d is too early.
    res = api.receive_factory(l3["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_FACTORY_LEAD_TIME_UNMET, expected_status=409)

    set_clock("2026-08-07T09:00:00Z")  # +4 days
    received3 = validate_success(api.receive_factory(l3["id"], MANAGER), 200)
    assert received3["sourcing_status"] == "FACTORY_RECEIVED"

    stock_after = get_success_data(api.get_branch_stock(stock["id"], MANAGER))
    assert stock_after["on_hand_qty"] == 3, (
        f"three factory receipts land 3 units on the shelf; got {stock_after['on_hand_qty']}")
