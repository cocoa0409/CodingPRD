"""Entity state machines: retail order branching, standing-order cycling, batch/order
precondition enforcement, pre-order deposit gating, and stock/markdown cascades."""
import pytest

from test_helpers import (
    api_client as _ac,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    line_item, wholesale_line,
    create_product, create_production_day, create_wholesale_account,
    create_standing_order, create_planned_batch, create_cart, create_paid_order,
    create_pre_order,
    setup_selling_day_with_baked_batch,
    setup_baking_day_with_planned_batch,
    setup_open_day_with_planned_batch,
    setup_account_with_standing_order,
)

ADMIN = TEST_USERS["shop_admin_headers"]
BAKER = TEST_USERS["bake_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]
DRIVER = TEST_USERS["route_driver_headers"]


# =====================================================================
# Difficulty/non_linear_state_machine/retail_order_branching_paid_to_void_or_refund (2)
# =====================================================================
def _two_paid_orders():
    day, product, batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=48)
    o_void = create_paid_order(day["id"], [line_item(product["id"], 12)])
    o_refund = create_paid_order(day["id"], [line_item(product["id"], 12)])
    return day, batch, o_void, o_refund


def test_paid_order_branches_to_void_and_refund(api):
    """PRD §3.4: "Orders follow CART -> PAID, and from PAID either onward to REFUNDED
    or aside to VOIDED; VOIDED and REFUNDED are both terminal."

    Design: Difficulty/non_linear_state_machine/retail_order_branching_paid_to_void_or_refund
    """
    day, _batch, o_void, o_refund = _two_paid_orders()
    voided = validate_success(_ac.void_retail_order(day["id"], o_void["id"], CASHIER))
    refunded = validate_success(_ac.refund_retail_order(day["id"], o_refund["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    assert refunded["status"] == "REFUNDED"


def test_void_and_refund_both_restore_full_batch_stock(api):
    """PRD §3.5: "Both reversals restore each line product's batch sold_qty and
    remaining_qty (and restore markdown_sold_qty for marked-down lines)."

    Design: Difficulty/non_linear_state_machine/retail_order_branching_paid_to_void_or_refund
    """
    day, batch, o_void, o_refund = _two_paid_orders()
    validate_success(_ac.void_retail_order(day["id"], o_void["id"], CASHIER))
    validate_success(_ac.refund_retail_order(day["id"], o_refund["id"], ADMIN))
    fetched = validate_success(_ac.get_bake_batch(day["id"], batch["id"], BAKER))
    assert fetched["remaining_qty"] == 48, (
        f"both reversals restore stock; baked 48, none net sold; got {fetched['remaining_qty']}")


# =====================================================================
# Difficulty/non_linear_state_machine/standing_order_cyclic_active_pause_active (2)
# =====================================================================
def _active_standing_order():
    _account, so, _products = setup_account_with_standing_order([("GLAZED", 12)],
                                                               delivery_dow=2)
    return so


def test_standing_order_pause_then_resume_cycles_to_active(api):
    """PRD §3.6: "A standing order is ACTIVE on creation and may move ACTIVE -> PAUSED
    (pause), PAUSED -> ACTIVE (resume), or from either ACTIVE or PAUSED to the terminal
    CANCELLED (cancel)."

    Design: Difficulty/non_linear_state_machine/standing_order_cyclic_active_pause_active
    """
    so = _active_standing_order()
    paused = validate_success(_ac.pause_standing_order(so["id"], ADMIN))
    assert paused["status"] == "PAUSED"
    resumed = validate_success(_ac.resume_standing_order(so["id"], ADMIN))
    assert resumed["status"] == "ACTIVE"


def test_standing_order_pause_sets_paused_status(api):
    """PRD §3.6: "A standing order is ACTIVE on creation and may move ACTIVE -> PAUSED
    (pause), PAUSED -> ACTIVE (resume), or from either ACTIVE or PAUSED to the terminal
    CANCELLED (cancel)."

    Design: Difficulty/non_linear_state_machine/standing_order_cyclic_active_pause_active
    """
    so = _active_standing_order()
    assert so["status"] == "ACTIVE"
    paused = validate_success(_ac.pause_standing_order(so["id"], ADMIN))
    assert paused["status"] == "PAUSED", (
        f"ACTIVE -> PAUSED on pause; got {paused['status']}")


# =====================================================================
# Corner/state_machines/bake_from_non_baking_day_rejected  (1)
# =====================================================================
def test_bake_while_day_open_rejected(api):
    """PRD §3.3: "When the dough is in the oven, the bake manager bakes the batch, which
    requires the batch to be PLANNED (else ERR_BATCH_INVALID_STATE), requires the parent
    day to be BAKING (else ERR_DAY_INVALID_STATE)."

    Design: Corner/state_machines/bake_from_non_baking_day_rejected
    """
    day, _product, batch = setup_open_day_with_planned_batch("GLAZED", par_qty=30)
    resp = _ac.bake_batch(day["id"], batch["id"], {"baked_qty": 30}, BAKER)
    validate_error(resp, ApiErrorId.ERR_DAY_INVALID_STATE.value)


# =====================================================================
# Corner/state_machines/pay_already_paid_order_rejected  (1)
# =====================================================================
def test_pay_already_paid_order_rejected(api):
    """PRD §3.4: "Paying a cart is performed by a Cashier and moves it CART -> PAID. It
    requires the order to be in CART (else ERR_ORDER_INVALID_STATE)."

    Design: Corner/state_machines/pay_already_paid_order_rejected
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=30)
    order = create_paid_order(day["id"], [line_item(product["id"], 6)])
    resp = _ac.pay_retail_order(day["id"], order["id"], CASHIER)
    validate_error(resp, ApiErrorId.ERR_ORDER_INVALID_STATE.value)


# =====================================================================
# Corner/state_machines/start_baking_no_batches_rejected  (1)
# =====================================================================
def test_start_baking_with_no_batches_rejected(api):
    """PRD §3.2: "A BakeManager starts baking, moving the day from OPEN to BAKING; this
    requires the day to currently be OPEN (else ERR_DAY_INVALID_STATE) and requires at
    least one bake batch to exist for the day (else ERR_NO_BATCHES)."

    Design: Corner/state_machines/start_baking_no_batches_rejected
    """
    day = create_production_day()
    resp = _ac.start_baking(day["id"], BAKER)
    validate_error(resp, ApiErrorId.ERR_NO_BATCHES.value)


# =====================================================================
# Corner/state_machines/preorder_confirm_without_deposit_rejected  (1)
# =====================================================================
def _catering_pre_order_4050():
    glazed = create_product("GLAZED")
    sesame = create_product("SESAME")
    every = create_product("EVERYTHING")
    account = create_wholesale_account(name="Party Co", discount_pct=0.10)
    day = create_production_day()
    pre = create_pre_order(
        account["id"], day["id"], "2027-08-04T07:00:00Z", "2027-08-04T08:00:00Z",
        [wholesale_line(glazed["id"], 23), wholesale_line(sesame["id"], 3),
         wholesale_line(every["id"], 4)])
    return pre


def test_confirm_preorder_without_deposit_rejected(api):
    """PRD §3.8: "A ShopAdmin confirms a pre-order (REQUESTED -> CONFIRMED), which
    requires the pre-order to be REQUESTED (else ERR_PREORDER_INVALID_STATE), requires
    deposit_paid_cents to have reached deposit_due_cents (else ERR_DEPOSIT_NOT_MET,
    HTTP 402)."

    Design: Corner/state_machines/preorder_confirm_without_deposit_rejected
    """
    pre = _catering_pre_order_4050()
    assert pre["deposit_due_cents"] == 1013
    resp = _ac.confirm_pre_order(pre["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_MET.value)


# =====================================================================
# Corner/state_machines/preorder_confirm_after_deposit_succeeds  (1)
# =====================================================================
def test_confirm_preorder_after_deposit_succeeds(api):
    """PRD §3.8: "Deposits are recorded incrementally: a ShopAdmin or owning
    WholesaleClient records a deposit payment by supplying an amount_cents, which raises
    deposit_paid_cents. A ShopAdmin confirms a pre-order (REQUESTED -> CONFIRMED), which
    requires the pre-order to be REQUESTED (else ERR_PREORDER_INVALID_STATE), requires
    deposit_paid_cents to have reached deposit_due_cents."

    Design: Corner/state_machines/preorder_confirm_after_deposit_succeeds
    """
    pre = _catering_pre_order_4050()
    validate_success(_ac.record_deposit(pre["id"], {"amount_cents": 1013}, ADMIN))
    confirmed = validate_success(_ac.confirm_pre_order(pre["id"], ADMIN))
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["deposit_paid_cents"] == 1013


# =====================================================================
# Corner/calculations/insufficient_full_price_stock_rejected  (1)
# =====================================================================
def test_pay_full_price_line_over_stock_rejected(api):
    """PRD §3.4: "for every line, the product's batch must have remaining_qty at least
    as large as the line quantity (else ERR_INSUFFICIENT_STOCK)."

    Design: Corner/calculations/insufficient_full_price_stock_rejected
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=30, baked_qty=30)
    order = create_cart(day["id"], [line_item(product["id"], 31)])
    resp = _ac.pay_retail_order(day["id"], order["id"], CASHIER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


# =====================================================================
# Difficulty/cross_entity_state_dependency/markdown_line_requires_batch_marked_down (2)
# =====================================================================
def test_markdown_line_against_baked_batch_rejected(api):
    """PRD §3.4: "for every marked_down line, the product's batch on the day must be in
    MARKED_DOWN status and have remaining_qty at least as large as the line quantity
    (else ERR_INSUFFICIENT_MARKDOWN_STOCK)."

    Design: Difficulty/cross_entity_state_dependency/markdown_line_requires_batch_marked_down
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=30)
    order = create_cart(day["id"], [line_item(product["id"], 3, marked_down=True)])
    resp = _ac.pay_retail_order(day["id"], order["id"], CASHIER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MARKDOWN_STOCK.value)


def test_markdown_line_against_baked_batch_leaves_order_cart(api):
    """PRD §3.4: "for every marked_down line, the product's batch on the day must be in
    MARKED_DOWN status and have remaining_qty at least as large as the line quantity
    (else ERR_INSUFFICIENT_MARKDOWN_STOCK)."

    Design: Difficulty/cross_entity_state_dependency/markdown_line_requires_batch_marked_down
    """
    day, product, _batch = setup_selling_day_with_baked_batch("GLAZED", par_qty=30)
    order = create_cart(day["id"], [line_item(product["id"], 3, marked_down=True)])
    validate_error(_ac.pay_retail_order(day["id"], order["id"], CASHIER),
                   ApiErrorId.ERR_INSUFFICIENT_MARKDOWN_STOCK.value)
    fetched = validate_success(_ac.get_retail_order(day["id"], order["id"], CASHIER))
    assert fetched["status"] == "CART", (
        f"rejected pay leaves order CART; got {fetched['status']}")


# =====================================================================
# Corner/errors/account_invalid_state_reactivate_active_rejected  (1)
# =====================================================================
def test_reactivate_active_account_rejected(api):
    """PRD §3.6: "A ShopAdmin suspends an active account (ACTIVE -> SUSPENDED, requiring
    it be ACTIVE, else ERR_ACCOUNT_INVALID_STATE) and reactivates a suspended one
    (SUSPENDED -> ACTIVE, requiring it be SUSPENDED, else ERR_ACCOUNT_INVALID_STATE)."

    Design: Corner/errors/account_invalid_state_reactivate_active_rejected
    """
    account = create_wholesale_account(discount_pct=0.15)
    resp = _ac.reactivate_account(account["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_INVALID_STATE.value)


# =====================================================================
# Corner/validations/invalid_bake_qty_zero_rejected  (1)
# =====================================================================
def test_bake_with_zero_qty_rejected(api):
    """PRD §3.3: "requires the supplied actual baked_qty to be at least 1 (else
    ERR_INVALID_BAKE_QTY)."

    Design: Corner/validations/invalid_bake_qty_zero_rejected
    """
    day, _product, batch = setup_baking_day_with_planned_batch("GLAZED", par_qty=30)
    resp = _ac.bake_batch(day["id"], batch["id"], {"baked_qty": 0}, BAKER)
    validate_error(resp, ApiErrorId.ERR_INVALID_BAKE_QTY.value)
