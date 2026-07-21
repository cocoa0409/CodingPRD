"""Point-of-sale totals, per-line tax rounding, redemption, and loyalty accrual.

Difficulty: combinatorial_formula (tax rounding, tiered loyalty cap),
priority_pair_validation_conflict (item-availability beats credit). Corner: calculations,
validations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    create_member, create_product, create_inventory_item, grant_store_credit,
    make_sale, sale_line,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Difficulty: sale tax rounded per line then summed ────────────────────
def test_sale_tax_rounded_per_line_then_summed(api):
    """PRD §3.8: "for each line, multiply its qty by its unit_price_cents by the tax rate
    of 0.0725 and round that line's tax half-up to whole cents, then sum the rounded
    per-line taxes — this round-then-sum order is binding and must not be collapsed into a
    single rounding of the grand total."

    Design: Difficulty/combinatorial_formula/sale_tax_rounded_per_line_then_summed
    """
    member = create_member(full_name="Sam")
    product = create_product(base_price_cents=1000)
    it1 = create_inventory_item(product["id"], "B")
    it2 = create_inventory_item(product["id"], "B")
    lines = [sale_line(it1["id"], 1000, 1), sale_line(it2["id"], 1000, 1)]
    sale = validate_success(make_sale(member["id"], lines), 201)
    assert sale["tax_total_cents"] == 146


def test_sale_subtotal_and_total_from_lines(api):
    """PRD §3.8: "The subtotal_cents is the sum over the lines of each line's qty
    multiplied by its unit_price_cents." PRD §3.8: "The total_cents is subtotal_cents plus
    tax_total_cents."

    Design: Difficulty/combinatorial_formula/sale_tax_rounded_per_line_then_summed
    """
    member = create_member(full_name="Sam")
    product = create_product(base_price_cents=1000)
    it1 = create_inventory_item(product["id"], "B")
    it2 = create_inventory_item(product["id"], "B")
    lines = [sale_line(it1["id"], 1000, 1), sale_line(it2["id"], 1000, 1)]
    sale = validate_success(make_sale(member["id"], lines), 201)
    assert sale["subtotal_cents"] == 2000
    assert sale["total_cents"] == 2146


# ─── Difficulty: loyalty tiered with cap and credit exclusion ─────────────
def test_loyalty_points_capped_at_max(api):
    """PRD §3.8: "The loyalty_points_earned is computed by multiplying that cash portion
    (in cents) by the member's tier rate (1.0 for STANDARD, 1.5 for SILVER, 2.0 for GOLD),
    dividing by 100, and taking the floor to a whole number of points, then capping the
    result at a maximum of 5000 points per sale."

    Design: Difficulty/combinatorial_formula/loyalty_points_tiered_with_cap_and_credit_exclusion
    """
    member = create_member(full_name="Gina", tier="GOLD")
    grant_store_credit(member["id"], 21750)
    product = create_product(kind="CONSOLE", base_price_cents=300000)
    it1 = create_inventory_item(product["id"], "A")
    sale = validate_success(
        make_sale(member["id"], [sale_line(it1["id"], 300000, 1)],
                  redeem_store_credit_cents=21750), 201)
    assert sale["loyalty_points_earned"] == 5000


def test_loyalty_credit_excluded_and_member_updated(api):
    """PRD §3.8: "Redemption. The store credit actually applied is the lesser of
    redeem_store_credit_cents and total_cents." PRD §3.8: "The amount_due_cents is
    total_cents minus the applied credit." PRD §3.8: "The earned points are pinned on the
    sale as loyalty_points_earned and added to the member's cumulative loyalty_points."

    Design: Difficulty/combinatorial_formula/loyalty_points_tiered_with_cap_and_credit_exclusion
    """
    member = create_member(full_name="Gina", tier="GOLD")
    grant_store_credit(member["id"], 21750)
    product = create_product(kind="CONSOLE", base_price_cents=300000)
    it1 = create_inventory_item(product["id"], "A")
    sale = validate_success(
        make_sale(member["id"], [sale_line(it1["id"], 300000, 1)],
                  redeem_store_credit_cents=21750), 201)
    assert sale["total_cents"] == 321750
    assert sale["amount_due_cents"] == 300000
    fetched = validate_success(api.get_member(member["id"], CLERK), 200)
    assert fetched["loyalty_points"] == 5000


# ─── Difficulty: item-not-available beats insufficient-credit ─────────────
def test_sale_item_not_available_beats_insufficient_credit(api):
    """PRD §2.11: "on a sale, item availability is checked before the store-credit
    sufficiency check."
    PRD §3.8: "Every line's inventory item must be AVAILABLE; if any targeted item is not
    AVAILABLE, the sale is rejected with ERR_ITEM_NOT_AVAILABLE (HTTP 409) before any
    totals are computed."

    Design: Difficulty/priority_pair_validation_conflict/sale_item_not_available_beats_insufficient_credit
    """
    member = create_member(full_name="Dana")
    product = create_product(base_price_cents=1000)
    it1 = create_inventory_item(product["id"], "C")
    validate_success(make_sale(member["id"], [sale_line(it1["id"], 1000, 1)]), 201)  # item now SOLD

    res = make_sale(member["id"], [sale_line(it1["id"], 1000, 1)], redeem_store_credit_cents=500)
    validate_error(res, "ERR_ITEM_NOT_AVAILABLE", expected_status=409)


def test_sale_availability_precedence_not_credit_error(api):
    """PRD §2.11: "on a sale, item availability is checked before the store-credit
    sufficiency check."

    Design: Difficulty/priority_pair_validation_conflict/sale_item_not_available_beats_insufficient_credit
    """
    member = create_member(full_name="Dana")
    product = create_product(base_price_cents=1000)
    it1 = create_inventory_item(product["id"], "C")
    validate_success(make_sale(member["id"], [sale_line(it1["id"], 1000, 1)]), 201)

    res = make_sale(member["id"], [sale_line(it1["id"], 1000, 1)], redeem_store_credit_cents=500)
    assert res.status_code == 409
    assert res.json()["data"]["error_id"] != "ERR_INSUFFICIENT_STORE_CREDIT"


# ─── Corner: calculations / standard-tier points, no redemption ───────────
def test_sale_no_redemption_earns_standard_points(api):
    """PRD §3.8: "Loyalty accrues only on the cash portion of the sale — the total_cents
    minus the applied credit."
    PRD §3.8: "multiplying that cash portion (in cents) by the member's tier rate (1.0 for
    STANDARD, 1.5 for SILVER, 2.0 for GOLD), dividing by 100, and taking the floor to a
    whole number of points."

    Design: Corner/calculations/sale_no_redemption_earns_standard_tier_points
    """
    member = create_member(full_name="Std")
    product = create_product(base_price_cents=10000)
    it1 = create_inventory_item(product["id"], "A")
    sale = validate_success(make_sale(member["id"], [sale_line(it1["id"], 10000, 1)]), 201)
    assert sale["tax_total_cents"] == 725
    assert sale["total_cents"] == 10725
    assert sale["loyalty_points_earned"] == 107


# ─── Corner: validations / redeem exceeds balance ─────────────────────────
def test_sale_redeem_exceeds_balance_rejected(api):
    """PRD §3.8: "Before applying, the requested redeem_store_credit_cents must not exceed
    the member's current store_credit_balance_cents; if it does, the sale is rejected with
    ERR_INSUFFICIENT_STORE_CREDIT (HTTP 402)."

    Design: Corner/validations/sale_redeem_exceeds_balance_returns_402
    """
    member = create_member(full_name="Ins")
    product = create_product(base_price_cents=1000)
    it1 = create_inventory_item(product["id"], "A")
    res = make_sale(member["id"], [sale_line(it1["id"], 1000, 1)], redeem_store_credit_cents=500)
    validate_error(res, "ERR_INSUFFICIENT_STORE_CREDIT", expected_status=402)
