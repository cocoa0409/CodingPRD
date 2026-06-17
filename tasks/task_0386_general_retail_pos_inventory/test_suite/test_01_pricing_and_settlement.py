"""Pricing engine, tendering, and cash reconciliation.

Covers the pinned six-step pricing order, sum-then-round tax, BOGO/percent/amount
promotions, loyalty redemption interaction, split tender settlement, cash change,
and end-of-day reconciliation.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_store, create_product, create_promotion, open_cash_session,
    create_loyalty_account, grant_points, create_sale, add_tender,
    setup_store_product_stock, get_sale, get_cash_session,
)

SM = TEST_USERS["store_manager_headers"]
CA = TEST_USERS["cashier_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Combinatorial pricing: sum-then-round tax (mode b) and pinned eval order (mode c)
# ─────────────────────────────────────────────────────────────────────────────

def test_tax_sum_then_round_across_two_taxable_lines(api):
    """PRD §2.6: "Critically, when a sale spans several taxable lines, the taxable
    bases of all lines are summed first and the half-up rounding is applied exactly
    once to that total."

    Design: Difficulty/combinatorial_formula/tax_sum_then_round_pinned_order_mode_b
    """
    store = create_store("TX1", tax_rate_bps=875)
    p1 = create_product("P1-TX", "B1-TX", list_price_cents=100, name="P1")
    p2 = create_product("P2-TX", "B2-TX", list_price_cents=109, name="P2")
    open_cash_session(store["id"])

    sale = create_sale(store["id"], [
        {"product_id": p1["id"], "quantity": 1},
        {"product_id": p2["id"], "quantity": 1},
    ])
    assert sale["merchandise_subtotal_cents"] == 209
    assert sale["tax_cents"] == 18, (
        f"sum-then-round must yield 18, got {sale['tax_cents']} "
        "(per-line rounding would be 19)"
    )
    assert sale["total_due_cents"] == 227


def test_tax_total_due_is_subtotal_plus_summed_tax(api):
    """PRD §3.3: "**Sixth**, `total_due_cents` is the post-discount subtotal minus
    `loyalty_redeemed_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/tax_sum_then_round_pinned_order_mode_b
    """
    store = create_store("TX2", tax_rate_bps=875)
    p1 = create_product("P1-TX2", "B1-TX2", list_price_cents=100, name="P1")
    p2 = create_product("P2-TX2", "B2-TX2", list_price_cents=109, name="P2")
    open_cash_session(store["id"])

    sale = create_sale(store["id"], [
        {"product_id": p1["id"], "quantity": 1},
        {"product_id": p2["id"], "quantity": 1},
    ])
    # No promo, no redemption: total_due == subtotal + summed-then-rounded tax.
    assert sale["discount_cents"] == 0
    assert sale["loyalty_redeemed_cents"] == 0
    assert sale["total_due_cents"] == sale["merchandise_subtotal_cents"] + sale["tax_cents"]
    assert sale["total_due_cents"] == 227


def test_pricing_evaluation_order_discount_then_redeem_then_tax(api):
    """PRD §3.3: "Pricing follows a strictly pinned six-step order, all in integer
    cents."
    PRD §3.3: "**Third**, the post-discount subtotal is the merchandise subtotal minus
    `discount_cents`."
    PRD §3.3: "**Fourth**, loyalty redemption is applied only when `redeem_points` is
    greater than zero: `loyalty_redeemed_cents` is the smaller of `redeem_points` (each
    point worth one cent) and the post-discount subtotal."
    PRD §3.3: "**Sixth**, `total_due_cents` is the post-discount subtotal minus
    `loyalty_redeemed_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/pricing_evaluation_order_discount_then_redeem_then_tax_mode_c
    """
    store = create_store("ORD1", tax_rate_bps=1000)
    product = create_product("PO-ORD", "BO-ORD", list_price_cents=1000)
    account = create_loyalty_account(phone="555-ord")
    grant_points(account["id"], 200)
    create_promotion("AMTORD", "AMOUNT_OFF", 800, min_subtotal_cents=0, stackable=True)
    open_cash_session(store["id"])

    sale = create_sale(
        store["id"], [{"product_id": product["id"], "quantity": 5}],
        loyalty_account_id=account["id"], promo_code="AMTORD", redeem_points=200)
    assert sale["discount_cents"] == 800
    assert sale["loyalty_redeemed_cents"] == 200
    assert sale["tax_cents"] == 400
    assert sale["total_due_cents"] == 4400


def test_pricing_order_merchandise_subtotal_and_post_discount(api):
    """PRD §3.3: "**First**, the `merchandise_subtotal_cents` is the sum over all lines
    of the product's `list_price_cents` times the line `quantity`."
    PRD §3.3: "For an `AMOUNT_OFF` promotion, `discount_cents` is the smaller of the
    promotion's `value` (cents off) and the merchandise subtotal."

    Design: Difficulty/combinatorial_formula/pricing_evaluation_order_discount_then_redeem_then_tax_mode_c
    """
    store = create_store("ORD2", tax_rate_bps=1000)
    product = create_product("PO-ORD2", "BO-ORD2", list_price_cents=1000)
    account = create_loyalty_account(phone="555-ord2")
    grant_points(account["id"], 200)
    create_promotion("AMTORD2", "AMOUNT_OFF", 800, min_subtotal_cents=0, stackable=True)
    open_cash_session(store["id"])

    sale = create_sale(
        store["id"], [{"product_id": product["id"], "quantity": 5}],
        loyalty_account_id=account["id"], promo_code="AMTORD2", redeem_points=200)
    # 5 x 1000 = 5000 merchandise; AMOUNT_OFF 800 -> post-discount 4200.
    assert sale["merchandise_subtotal_cents"] == 5000
    assert sale["merchandise_subtotal_cents"] - sale["discount_cents"] == 4200


# ─────────────────────────────────────────────────────────────────────────────
# Promotion mechanics
# ─────────────────────────────────────────────────────────────────────────────

def test_bogo_50_discount_on_even_quantity(api):
    """PRD §3.3: "For a `BOGO_50` promotion, the promotion's `value` is ignored and
    instead, for each product line, the number of qualifying pairs is the line
    `quantity` divided by two and floored, and the discount for that line is that pair
    count multiplied by half of the product's `list_price_cents` floored;
    `discount_cents` is the sum of those per-line amounts (fifty percent off the
    cheaper — here, equal — unit of each qualifying pair)."

    Design: Corner/calculations/bogo_50_discount_correct_on_even_quantity
    """
    store = create_store("BG1", tax_rate_bps=0)
    product = create_product("PBG", "BBG", list_price_cents=500)
    create_promotion("BOGO", "BOGO_50", 0, min_subtotal_cents=0, stackable=False)
    open_cash_session(store["id"])

    sale = create_sale(
        store["id"], [{"product_id": product["id"], "quantity": 4}],
        promo_code="BOGO")
    assert sale["merchandise_subtotal_cents"] == 2000
    assert sale["discount_cents"] == 500
    assert sale["total_due_cents"] == 1500


def test_percent_off_below_min_subtotal_rejected(api):
    """PRD §3.4: "If the resolved promotion is not `ACTIVE`, or the
    `merchandise_subtotal_cents` is below the promotion's `min_subtotal_cents`, the
    promo cannot apply and the request is rejected with `ERR_PROMO_NOT_APPLICABLE`."

    Design: Corner/calculations/percent_off_below_min_subtotal_rejected
    """
    store = create_store("PM1", tax_rate_bps=0)
    product = create_product("PPM", "BPM", list_price_cents=1000)
    create_promotion("PCT20", "PERCENT_OFF", 20, min_subtotal_cents=5000, stackable=False)
    open_cash_session(store["id"])

    resp = api.create_sale(
        {"store_id": store["id"], "kind": "SALE", "promo_code": "PCT20",
         "lines": [{"product_id": product["id"], "quantity": 3}]}, CA)
    validate_error(resp, ApiErrorId.ERR_PROMO_NOT_APPLICABLE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Tendering, split payment, cash change, settlement
# ─────────────────────────────────────────────────────────────────────────────

def test_cash_overpayment_yields_change_due_on_closing_tender(api):
    """PRD §3.5: "For a `SALE`, once the captured tenders bring `tendered_cents` to at
    least `total_due_cents`, the sale moves `TENDERING → SETTLED`; if the customer
    overpays in cash, the excess is returned as `change_due_cents` on that closing cash
    tender."

    Design: Corner/calculations/cash_overpayment_yields_change_due_on_closing_tender
    """
    s = setup_store_product_stock("CH1", "PCH", "BCH", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 1}])
    tender = validate_success(
        add_tender(sale["id"], "CASH", 1500, sale["version"]), expected_status=201)
    assert tender["change_due_cents"] == 500
    assert tender["amount_cents"] == 1500

    settled = get_sale(sale["id"])
    assert settled["settlement_status"] == "SETTLED"
    assert settled["stock_status"] == "COMMITTED"


def test_split_tender_settles_at_exact_total(api):
    """PRD §3.5: "Each subsequent split tender, while the running tender total has not
    yet reached the amount due, keeps the sale in `TENDERING` and appends another
    `TenderLine`; each appended tender updates `tendered_cents` and increments the
    sale's `version` by one."
    PRD §3.5: "For a `SALE`, once the captured tenders bring `tendered_cents` to at
    least `total_due_cents`, the sale moves `TENDERING → SETTLED`; if the customer
    overpays in cash, the excess is returned as `change_due_cents` on that closing cash
    tender."

    Design: Corner/calculations/split_tender_settles_at_exact_total
    """
    s = setup_store_product_stock("SP1", "PSP", "BSP", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 2}])
    validate_success(add_tender(sale["id"], "CARD", 1200, sale["version"]),
                     expected_status=201)
    mid = get_sale(sale["id"])
    assert mid["settlement_status"] == "TENDERING"
    validate_success(add_tender(sale["id"], "CASH", 800, mid["version"]),
                     expected_status=201)
    final = get_sale(sale["id"])
    assert final["tendered_cents"] == 2000
    assert final["settlement_status"] == "SETTLED"
    assert final["stock_status"] == "COMMITTED"


def test_non_cash_overtender_rejected(api):
    """PRD §3.5: "On a non-cash tender, over-collecting beyond `total_due_cents` is not
    allowed — only `CASH` may exceed the amount due, yielding change — and a `CARD`,
    `STORE_CREDIT`, or `GIFT_CARD` tender that would over-collect on a `SALE` is
    rejected with `ERR_OVERTENDER`."

    Design: Corner/validations/non_cash_overtender_rejected
    """
    s = setup_store_product_stock("OT1", "POT", "BOT", on_hand=5,
                                  list_price_cents=1000)
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 2}])
    resp = add_tender(sale["id"], "CARD", 2500, sale["version"])
    validate_error(resp, ApiErrorId.ERR_OVERTENDER.value)


def test_cash_reconciliation_variance_correct(api):
    """PRD §3.2: "`expected_cash_cents` is the `opening_float_cents` plus the sum of the
    positive amounts of cash tenders on settled bound sales, minus the sum of those
    tenders' change-due amounts, plus the sum of the negative amounts of cash refund
    tenders on settled bound sales (negatives reduce the drawer)."
    PRD §3.2: "The signed `variance_cents` is then the counted cash minus the expected
    cash."

    Design: Corner/calculations/cash_reconciliation_variance_correct
    """
    s = setup_store_product_stock("RX1", "PRX", "BRX", on_hand=5,
                                  list_price_cents=1000, opening_float_cents=10000)
    sess_id = s["session"]["id"]
    sale = create_sale(s["store"]["id"],
                       [{"product_id": s["product"]["id"], "quantity": 1}])
    get_success_data(add_tender(sale["id"], "CASH", 1500, sale["version"]))
    get_success_data(api.request_close_cash_session(sess_id, SM))

    reconciled = validate_success(
        api.reconcile_cash_session(sess_id, {"counted_cash_cents": 10800}, SM))
    assert reconciled["expected_cash_cents"] == 11000, (
        "10000 float + 1500 collected - 500 change == 11000"
    )
    assert reconciled["variance_cents"] == -200
    assert reconciled["status"] == "RECONCILED"
