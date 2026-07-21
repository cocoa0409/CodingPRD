"""Sales orders: trade-in appraisal, loyalty pricing, tax/credit totals,
recall blocking, reversal conservation, and the inventory reserve/release cycle.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    complete_sale,
    new_inventory_item,
    new_product,
    open_sales_order,
    recall_product,
    setup_reserved_sales_order,
    validate_error,
    validate_paginated,
    validate_success,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ───────────────────── dual-variant trade-in appraisal ─────────────────────
def test_trade_in_estimate_is_schedule_value_and_final_is_manager_value(api):
    """PRD §3.3: "On success the order enters `RESERVED`, the inventory item moves
    `IN_STOCK → RESERVED`, and a provisional `trade_in_estimate_cents` is set from a
    fixed condition schedule — 40,000 cents for a `GOOD` machine, 25,000 cents for
    `FAIR`, 10,000 cents for `POOR`, and 0 when there is no trade-in."

    Design: Difficulty/dual_variant_calc/trade_in_estimate_vs_final_appraisal
    """
    _cust, _prod, _item, so = setup_reserved_sales_order(
        credit=0, sale_price_cents=100000,
        trade_in_model="Old Singer", trade_in_condition="GOOD",
    )
    assert so["trade_in_estimate_cents"] == 40000
    completed = complete_sale(so["id"], trade_in_final_cents=48000)
    assert completed["trade_in_final_cents"] == 48000


def test_trade_in_grant_credits_the_final_not_the_estimate(api):
    """PRD §3.3: "It is the final figure, not the estimate, that is ultimately
    credited."

    Design: Difficulty/dual_variant_calc/trade_in_estimate_vs_final_appraisal
    """
    cust, _prod, _item, so = setup_reserved_sales_order(
        credit=0, sale_price_cents=100000,
        trade_in_model="Old Singer", trade_in_condition="GOOD",
    )
    complete_sale(so["id"], trade_in_final_cents=48000)
    buyer = validate_success(api.get_customer(cust["id"], SA), 200)
    assert buyer["store_credit_cents"] == 48000


# ─────────────── combinatorial sales total with nested min credit ──────────
def test_sales_total_nested_min_binds_to_bill(api):
    """PRD §3.3: "the taxable amount is `sale_price_cents` minus
    `loyalty_discount_cents`; the `tax_cents` is that taxable amount multiplied by
    the tax rate of 8%, rounded half up to whole cents; the `credit_applied_cents`
    is the smaller of the buyer's store-credit balance as it stood **before** this
    order and the sum of the taxable amount plus tax; and the `total_due_cents` is
    the taxable amount plus tax minus the credit applied."

    Design: Difficulty/combinatorial_formula/sales_total_nested_min_credit
    """
    _cust, _prod, _item, so = setup_reserved_sales_order(credit=200000, sale_price_cents=100000)
    completed = complete_sale(so["id"])
    assert completed["tax_cents"] == 8000
    assert completed["credit_applied_cents"] == 108000
    assert completed["total_due_cents"] == 0


def test_sales_total_consumes_credit_from_buyer_balance(api):
    """PRD §3.3: "The `credit_applied_cents` consumed by the order is deducted from
    the buyer's `store_credit_cents`."

    Design: Difficulty/combinatorial_formula/sales_total_nested_min_credit
    """
    cust, _prod, _item, so = setup_reserved_sales_order(credit=200000, sale_price_cents=100000)
    complete_sale(so["id"])
    buyer = validate_success(api.get_customer(cust["id"], SA), 200)
    assert buyer["store_credit_cents"] == 92000


# ─────────────── cross-entity recall dependency on completion ──────────────
def test_sale_completion_blocked_when_product_recalled(api):
    """PRD §3.3: "It is blocked when the reserved unit's product is `RECALLED`, in
    which case it fails with `ERR_PRODUCT_RECALLED`."

    Design: Difficulty/cross_entity_state_dependency/sale_complete_blocked_by_product_recall
    """
    _cust, prod, _item, so = setup_reserved_sales_order(credit=0, sale_price_cents=95000)
    recall_product(prod["id"], "Wiring defect")
    res = api.complete_sales_order(so["id"], {}, SA)
    validate_error(res, "ERR_PRODUCT_RECALLED", expected_status=409)


def test_sale_completion_blocked_by_recall_leaves_order_reserved(api):
    """PRD §3.3: "Completion requires the order to be `RESERVED`, else
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/sale_complete_blocked_by_product_recall
    """
    _cust, prod, _item, so = setup_reserved_sales_order(credit=0, sale_price_cents=95000)
    recall_product(prod["id"], "Wiring defect")
    api.complete_sales_order(so["id"], {}, SA)
    after = validate_success(api.get_sales_order(so["id"], SA), 200)
    assert after["status"] == "RESERVED"


# ────────────── compensating invariant: store credit conserved ─────────────
def test_sale_reversal_restores_store_credit_to_pre_sale(api):
    """PRD §3.3: "a `StoreManager` may reverse a `COMPLETED` order as a return: the
    order moves `COMPLETED → CANCELLED`, the sold unit returns `SOLD → IN_STOCK`,
    the `credit_applied_cents` originally consumed is added back to the buyer's
    `store_credit_cents`, and — if the order carried a trade-in — the
    `trade_in_final_cents` originally granted is clawed back out of the buyer's
    store credit."

    Design: Difficulty/compensating_invariant/sale_complete_cancel_store_credit_conserved
    """
    cust, _prod, _item, so = setup_reserved_sales_order(
        credit=30000, sale_price_cents=100000,
        trade_in_model="Old Bernina", trade_in_condition="GOOD",
    )
    completed = complete_sale(so["id"], trade_in_final_cents=48000)
    assert completed["credit_applied_cents"] == 30000
    reversed_order = validate_success(api.cancel_sales_order(so["id"], SM), 200)
    assert reversed_order["status"] == "CANCELLED"
    buyer = validate_success(api.get_customer(cust["id"], SA), 200)
    assert buyer["store_credit_cents"] == 30000


def test_sale_reversal_restores_lifetime_spend(api):
    """PRD §3.3: "Finally the buyer's `lifetime_spend_cents` is reduced by this
    order's `total_due_cents` and their `loyalty_tier` recomputed."

    Design: Difficulty/compensating_invariant/sale_complete_cancel_store_credit_conserved
    """
    cust, _prod, _item, so = setup_reserved_sales_order(
        credit=30000, sale_price_cents=100000,
        trade_in_model="Old Bernina", trade_in_condition="GOOD",
    )
    complete_sale(so["id"], trade_in_final_cents=48000)
    api.cancel_sales_order(so["id"], SM)
    buyer = validate_success(api.get_customer(cust["id"], SA), 200)
    assert buyer["lifetime_spend_cents"] == 0


# ─────────────── non-linear inventory reserve/release cycle ────────────────
def test_cancel_reserved_order_releases_item_to_in_stock(api):
    """PRD §3.3: "A `SalesAssociate` (or a `StoreManager`) may cancel a `RESERVED`
    order that has not yet completed: the order moves `RESERVED → CANCELLED` and the
    held inventory item is released `RESERVED → IN_STOCK`; no ledger movement is
    involved because none had occurred."

    Design: Difficulty/non_linear_state_machine/inventory_item_reserve_release_cycle
    """
    cust, _prod, item, so1 = setup_reserved_sales_order(credit=0, sale_price_cents=28000)
    cancelled = validate_success(api.cancel_sales_order(so1["id"], SA), 200)
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_inventory_item(item["id"], SA), 200)
    assert after["status"] == "IN_STOCK"


def test_released_item_can_be_reserved_again(api):
    """PRD §3.1: "Because a released unit can be reserved again by a fresh order, the
    `IN_STOCK → RESERVED → IN_STOCK` path is a genuine cycle."

    Design: Difficulty/non_linear_state_machine/inventory_item_reserve_release_cycle
    """
    cust, _prod, item, so1 = setup_reserved_sales_order(credit=0, sale_price_cents=28000)
    api.cancel_sales_order(so1["id"], SA)
    open_sales_order(cust["id"], item["id"], sale_price_cents=27000)
    after = validate_success(api.get_inventory_item(item["id"], SA), 200)
    assert after["status"] == "RESERVED"


def test_reserve_then_cancel_returns_item_to_in_stock_count(api):
    """PRD §3.3: "A `SalesAssociate` (or a `StoreManager`) may cancel a `RESERVED`
    order that has not yet completed: the order moves `RESERVED → CANCELLED` and the
    held inventory item is released `RESERVED → IN_STOCK`; no ledger movement is
    involved because none had occurred."

    Design: Difficulty/compensating_invariant/inventory_reserve_cancel_instock_count_conserved
    """
    _cust, _prod, item, so = setup_reserved_sales_order(credit=0, sale_price_cents=38000)
    cancelled = validate_success(api.cancel_sales_order(so["id"], SA), 200)
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_inventory_item(item["id"], SA), 200)
    assert after["status"] == "IN_STOCK"


def test_released_item_reappears_in_in_stock_listing(api):
    """PRD §3.1: "Inventory may be listed and filtered by `product_id` and by
    `status`, and fetched individually."

    Design: Difficulty/compensating_invariant/inventory_reserve_cancel_instock_count_conserved
    """
    _cust, prod, item, so = setup_reserved_sales_order(credit=0, sale_price_cents=38000)
    api.cancel_sales_order(so["id"], SA)
    data, _meta = validate_paginated(
        api.list_inventory_items(SA, params={"product_id": prod["id"], "status": "IN_STOCK"})
    )
    assert any(row["id"] == item["id"] for row in data)


# ──────────────────────────── corner instances ────────────────────────────
def test_completed_sale_recomputes_loyalty_tier_to_gold(api):
    """PRD §3.2: "the tier is `PLATINUM` when lifetime spend is at least 1,500,000
    cents, otherwise `GOLD` when lifetime spend is at least 500,000 cents, and
    otherwise `STANDARD`."

    Design: Corner/entities/customer_loyalty_tier_recompute_gold
    """
    cust, _prod, _item, so = setup_reserved_sales_order(
        credit=0, sale_price_cents=500000,
        product_overrides={"model_name": "Premium 5000", "category": "SEWING_MACHINE",
                           "brand": "Bernina", "msrp_cents": 600000},
        item_overrides={"acquisition_cost_cents": 400000, "list_price_cents": 600000},
    )
    completed = complete_sale(so["id"])
    assert completed["total_due_cents"] == 540000
    buyer = validate_success(api.get_customer(cust["id"], SA), 200)
    assert buyer["lifetime_spend_cents"] == 540000
    assert buyer["loyalty_tier"] == "GOLD"


def test_trade_in_estimate_fair_schedule(api):
    """PRD §3.3: "On success the order enters `RESERVED`, the inventory item moves
    `IN_STOCK → RESERVED`, and a provisional `trade_in_estimate_cents` is set from a
    fixed condition schedule — 40,000 cents for a `GOOD` machine, 25,000 cents for
    `FAIR`, 10,000 cents for `POOR`, and 0 when there is no trade-in."

    Design: Corner/calculations/trade_in_estimate_fair_schedule
    """
    _cust, _prod, _item, so = setup_reserved_sales_order(
        credit=0, sale_price_cents=85000,
        trade_in_model="Old Brother", trade_in_condition="FAIR",
    )
    assert so["trade_in_estimate_cents"] == 25000


def test_trade_in_out_of_band_rejected(api):
    """PRD §3.3: "the final figure must fall within 15,000 cents of the provisional
    estimate — that is, the absolute difference between `trade_in_final_cents` and
    `trade_in_estimate_cents` must be at most 15,000 cents — otherwise completion is
    rejected with `ERR_TRADE_IN_OUT_OF_BAND`."

    Design: Corner/errors/trade_in_out_of_band_rejected
    """
    _cust, _prod, _item, so = setup_reserved_sales_order(
        credit=0, sale_price_cents=100000,
        trade_in_model="Old", trade_in_condition="GOOD",
    )
    res = api.complete_sales_order(so["id"], {"trade_in_final_cents": 60000}, SA)
    validate_error(res, "ERR_TRADE_IN_OUT_OF_BAND", expected_status=409)
    after = validate_success(api.get_sales_order(so["id"], SA), 200)
    assert after["status"] == "RESERVED"


def test_complete_cancelled_sales_order_invalid_state(api):
    """PRD §3.3: "Completion requires the order to be `RESERVED`, else
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sales_order_complete_from_cancelled_invalid
    """
    _cust, _prod, _item, so = setup_reserved_sales_order(credit=0, sale_price_cents=29000)
    validate_success(api.cancel_sales_order(so["id"], SA), 200)
    res = api.complete_sales_order(so["id"], {}, SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_sales_order_nonexistent_customer_not_found(api):
    """PRD §2.10: "**Existence** — path resource ids are resolved left to right, and
    any foreign-key id in the body (`customer_id`, `inventory_item_id`,
    `product_id`, `class_session_id`) must reference an existing entity, else the
    corresponding not-found error (404)."

    Design: Corner/validations/sales_order_create_nonexistent_customer_not_found
    """
    prod = new_product(model_name="NF Model", category="VACUUM", brand="G", msrp_cents=30000)
    item = new_inventory_item(prod["id"], serial_number="SN-NF", acquisition_cost_cents=20000, list_price_cents=30000)
    res = api.create_sales_order(
        {"customer_id": NON_EXISTENT_UUID, "inventory_item_id": item["id"], "sale_price_cents": 29000},
        SA,
    )
    validate_error(res, "ERR_CUSTOMER_NOT_FOUND", expected_status=404)
