"""Loyalty earning/clawback, tier boundaries, redemption guards, and the
provisional-vs-final return refund dual variant.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_store, create_product, create_promotion, open_cash_session,
    create_loyalty_account, grant_points, create_sale, add_tender,
    settle_sale_cash, get_sale, get_loyalty_account,
    setup_store_product_stock, create_inventory_item_with_stock,
)

SM = TEST_USERS["store_manager_headers"]
CA = TEST_USERS["cashier_headers"]


def setup_store_product_stock_for(store, product, on_hand):
    """Attach an inventory item seeded to `on_hand` units for an already-created
    store and product. Returns the inventory item id."""
    return create_inventory_item_with_stock(store["id"], product["id"], on_hand)


# ─────────────────────────────────────────────────────────────────────────────
# Dual variant: return refund provisional vs final
# ─────────────────────────────────────────────────────────────────────────────

def test_return_refund_provisional_vs_final_diverge_on_amount_off(api):
    """PRD §3.7: "The **provisional** refund, shown as the estimated `total_due_cents`
    at creation, is built line by line: for each return line, the original line's
    effective unit price — its original net amount (post-discount, post-redemption)
    divided by its original quantity and floored per unit — is multiplied by the
    returned quantity, and its proportional original tax is added; these per-line
    figures are summed."
    PRD §3.7: "The system re-runs the original sale's pricing with the returned units
    removed and takes the difference between the original total due and that recomputed
    total due without the returned units."
    PRD §3.6: "When a `RETURN` or `EXCHANGE` settles, it transitions `PENDING →
    RESTOCKED`."

    Design: Difficulty/dual_variant_calc/return_refund_provisional_vs_final_diverge_on_amount_off_basket
    """
    store = create_store("S-RET", tax_rate_bps=0)
    product = create_product("P-RET", "BC-RET", list_price_cents=1000)
    setup_store_product_stock_for(store, product, on_hand=10)
    create_promotion("AMT800", "AMOUNT_OFF", 800, min_subtotal_cents=0, stackable=True)
    open_cash_session(store["id"])

    orig = settle_sale_cash(store["id"],
                            [{"product_id": product["id"], "quantity": 5}],
                            promo_code="AMT800")
    assert orig["total_due_cents"] == 4200

    ret = create_sale(
        store["id"], [{"product_id": product["id"], "quantity": 2,
                       "return_of_line_no": 1}],
        kind="RETURN", original_sale_id=orig["id"])
    assert ret["total_due_cents"] == -1680, (
        f"provisional per-unit floor must be -1680, got {ret['total_due_cents']}"
    )

    validate_success(add_tender(ret["id"], "CASH", -2000, ret["version"]),
                     expected_status=201)
    settled = get_sale(ret["id"])
    assert settled["total_due_cents"] == -2000, (
        f"final basket-delta refund must be -2000, got {settled['total_due_cents']}"
    )
    assert settled["settlement_status"] == "SETTLED"
    assert settled["stock_status"] == "RESTOCKED"


def test_return_provisional_estimate_differs_from_final(api):
    """PRD §3.7: "This estimate floors each unit independently and therefore ignores
    how a basket-level promotion or loyalty redemption was originally distributed."
    PRD §3.7: "This delta method captures exactly the promo and loyalty interaction
    that the per-unit floor cannot, so the two figures diverge whenever the original
    sale carried a promotion — especially `BOGO_50` or `AMOUNT_OFF` — or a loyalty
    redemption."

    Design: Difficulty/dual_variant_calc/return_refund_provisional_vs_final_diverge_on_amount_off_basket
    """
    store = create_store("S-RET2", tax_rate_bps=0)
    product = create_product("P-RET2", "BC-RET2", list_price_cents=1000)
    setup_store_product_stock_for(store, product, on_hand=10)
    create_promotion("AMT8B", "AMOUNT_OFF", 800, min_subtotal_cents=0, stackable=True)
    open_cash_session(store["id"])

    orig = settle_sale_cash(store["id"],
                            [{"product_id": product["id"], "quantity": 5}],
                            promo_code="AMT8B")
    ret = create_sale(
        store["id"], [{"product_id": product["id"], "quantity": 2,
                       "return_of_line_no": 1}],
        kind="RETURN", original_sale_id=orig["id"])
    provisional = ret["total_due_cents"]
    validate_success(add_tender(ret["id"], "CASH", -2000, ret["version"]),
                     expected_status=201)
    final = get_sale(ret["id"])["total_due_cents"]
    assert provisional == -1680
    assert final == -2000
    assert provisional != final, "provisional and final refunds diverge on AMOUNT_OFF basket"


def test_loyalty_points_earn_at_sale_then_clawback_at_return(api):
    """PRD §3.8: "The resulting `points_earned` credits both `points_balance` and
    `lifetime_points`."
    PRD §3.8: "On a `RETURN` settlement against the original sale, the points originally
    earned for the returned units are clawed back from `points_balance` only —
    `lifetime_points` is left untouched, so the multiplier never downgrades a member's
    tier — and any points the original sale had redeemed are restored to
    `points_balance`."

    Design: Difficulty/dual_variant_calc/loyalty_points_earn_at_sale_vs_clawback_at_return
    """
    store = create_store("LY1", tax_rate_bps=1000, loyalty_earn_rate_bps=100)
    product = create_product("P-LY", "BC-LY", list_price_cents=1000)
    setup_store_product_stock_for(store, product, on_hand=20)
    account = create_loyalty_account(phone="555-0001")
    grant_points(account["id"], 200)
    create_promotion("LYAMT", "AMOUNT_OFF", 800, min_subtotal_cents=0, stackable=True)
    open_cash_session(store["id"])

    orig = settle_sale_cash(
        store["id"], [{"product_id": product["id"], "quantity": 5}],
        loyalty_account_id=account["id"], promo_code="LYAMT", redeem_points=200)
    assert orig["total_due_cents"] == 4400

    after_sale = get_loyalty_account(account["id"])
    assert after_sale["points_balance"] == 40, (
        "granted 200 - redeemed 200 + earned 40 == 40"
    )
    assert after_sale["lifetime_points"] == 240

    ret = create_sale(
        store["id"], [{"product_id": product["id"], "quantity": 5,
                       "return_of_line_no": 1}],
        kind="RETURN", loyalty_account_id=account["id"], original_sale_id=orig["id"])
    validate_success(add_tender(ret["id"], "CASH", -4400, ret["version"]),
                     expected_status=201)

    after_return = get_loyalty_account(account["id"])
    assert after_return["points_balance"] == 200, (
        "earned 40 clawed back, redeemed 200 restored: 40 - 40 + 200 == 200"
    )
    assert after_return["lifetime_points"] == 240, "lifetime_points unchanged"


def test_loyalty_earn_credits_balance_and_lifetime_at_settlement(api):
    """PRD §3.8: "The eligible net is the sum, over the lines flagged `loyalty_eligible`,
    of each line's proportional share of the post-discount-minus-redemption amount —
    allocated in proportion to the line's pre-discount extended price, the same
    allocation basis used for tax, floored per line and then summed."
    PRD §3.8: "Base points are that eligible net multiplied by the store's
    `loyalty_earn_rate_bps`, divided by ten thousand, floored."
    PRD §3.8: "The resulting `points_earned` credits both `points_balance` and
    `lifetime_points`."

    Design: Difficulty/dual_variant_calc/loyalty_points_earn_at_sale_vs_clawback_at_return
    """
    store = create_store("LY2", tax_rate_bps=1000, loyalty_earn_rate_bps=100)
    product = create_product("P-LY2", "BC-LY2", list_price_cents=1000)
    setup_store_product_stock_for(store, product, on_hand=20)
    account = create_loyalty_account(phone="555-0021")
    grant_points(account["id"], 200)
    create_promotion("LYAMT2", "AMOUNT_OFF", 800, min_subtotal_cents=0, stackable=True)
    open_cash_session(store["id"])

    orig = settle_sale_cash(
        store["id"], [{"product_id": product["id"], "quantity": 5}],
        loyalty_account_id=account["id"], promo_code="LYAMT2", redeem_points=200)
    assert orig["points_earned"] == 40
    acct = get_loyalty_account(account["id"])
    assert acct["points_balance"] == 40, "granted 200 - redeemed 200 + earned 40"
    assert acct["lifetime_points"] == 240, "earn credits lifetime_points too"


# ─────────────────────────────────────────────────────────────────────────────
# Loyalty tier boundary precision
# ─────────────────────────────────────────────────────────────────────────────

def test_loyalty_tier_silver_inclusive_at_1000_lifetime_points(api):
    """PRD §3.8: "The boundaries are inclusive — exactly 1000 lifetime points is
    `SILVER`, exactly 5000 is `GOLD`, and 999 is `STANDARD`."

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_inclusive_at_1000_lifetime_points
    """
    account = create_loyalty_account(phone="555-0006")
    at999 = grant_points(account["id"], 999)
    assert at999["tier"] == "STANDARD", "999 lifetime points is STANDARD"
    at1000 = grant_points(account["id"], 1)
    assert at1000["tier"] == "SILVER", "1000 lifetime points is SILVER (>= inclusive)"


def test_loyalty_tier_standard_just_below_silver(api):
    """PRD §3.8: "The tier is recomputed from `lifetime_points` on every change, against
    inclusive thresholds: `lifetime_points` at or above 5000 is `GOLD`; at or above 1000
    (but below 5000) is `SILVER`; below 1000 is `STANDARD`."

    Design: Difficulty/boundary_precision_check/loyalty_tier_silver_inclusive_at_1000_lifetime_points
    """
    account = create_loyalty_account(phone="555-0996")
    at999 = grant_points(account["id"], 999)
    assert at999["lifetime_points"] == 999
    assert at999["tier"] == "STANDARD"


def test_insufficient_points_redeem_exceeds_balance(api):
    """PRD §3.4: "The points a customer asks to redeem cannot exceed the post-discount,
    pre-tax subtotal, and the attached account must actually hold at least the requested
    `redeem_points`; a request that asks to redeem more than the account's balance or
    more than the redeemable subtotal is rejected with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/insufficient_points_redeem_exceeds_balance
    """
    store = create_store("IP1", tax_rate_bps=0)
    product = create_product("PIP", "BIP", list_price_cents=1000)
    account = create_loyalty_account(phone="555-1001")
    grant_points(account["id"], 100)
    open_cash_session(store["id"])

    resp = api.create_sale(
        {"store_id": store["id"], "kind": "SALE", "loyalty_account_id": account["id"],
         "redeem_points": 1000,
         "lines": [{"product_id": product["id"], "quantity": 5}]}, CA)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)
