"""Tiered line pricing (pallet/case/each decomposition and boundaries) and
round-per-line-then-sum order tax, including the tax-exempt short circuit.
"""
from test_helpers import (
    validate_success,
    TEST_USERS, make_buyer_headers,
    product_payload,
    fixtures,
)

AM = TEST_USERS["account_manager_headers"]
WH = TEST_USERS["warehouse_headers"]


# --------------------------------------------------------------------------- #
# combinatorial_formula / tiered_pallet_case_each_decomposition
# --------------------------------------------------------------------------- #
def test_pallet_quantity_selects_pallet_tier(api):
    """PRD §3.3: "The `pricing_tier` records the highest whole tier reached: it is `PALLET` if
    there is at least one full pallet, otherwise `CASE` if there is at least one full case,
    otherwise `EACH`."

    Design: Difficulty/combinatorial_formula/tiered_pallet_case_each_decomposition
    """
    acct = fixtures.create_account(api, credit_terms="PREPAID")
    prod = fixtures.create_product(api, sku="WIDGET-1", unit_price_cents=500, case_qty=12,
                                   case_price_cents=5400, pallet_case_qty=10, pallet_price_cents=48000,
                                   on_hand_qty=1000, par_level=200, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    line = validate_success(
        api.add_order_line(order["id"], {"product_id": prod["id"], "quantity": 125},
                           make_buyer_headers(acct["id"])), 201,
    )
    assert line["pricing_tier"] == "PALLET"


def test_pallet_case_each_subtotal_decomposition(api):
    """PRD §3.3: "The `line_subtotal_cents` is the number of full pallets times `pallet_price_cents`,
    plus the number of full cases times `case_price_cents`, plus the leftover eaches times
    `unit_price_cents`."

    Design: Difficulty/combinatorial_formula/tiered_pallet_case_each_decomposition
    """
    acct = fixtures.create_account(api, credit_terms="PREPAID")
    prod = fixtures.create_product(api, sku="WIDGET-1b", unit_price_cents=500, case_qty=12,
                                   case_price_cents=5400, pallet_case_qty=10, pallet_price_cents=48000,
                                   on_hand_qty=1000, par_level=200, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    line = validate_success(
        api.add_order_line(order["id"], {"product_id": prod["id"], "quantity": 125},
                           make_buyer_headers(acct["id"])), 201,
    )
    # 125 = 1 pallet (120) + 0 cases + 5 eaches -> 48000 + 0 + 2500
    assert line["line_subtotal_cents"] == 50500


# --------------------------------------------------------------------------- #
# boundary_precision_check / line_qty_at_case_qty_selects_case_tier
# --------------------------------------------------------------------------- #
def test_quantity_equal_to_case_qty_selects_case_tier(api):
    """PRD §3.3: "a quantity of exactly `case_qty` (with no full pallet) is one full case and
    prices as `CASE`, while a quantity of `case_qty` minus one is all eaches and prices as `EACH`."

    Design: Difficulty/boundary_precision_check/line_qty_at_case_qty_selects_case_tier
    """
    acct = fixtures.create_account(api, credit_terms="PREPAID")
    prod = fixtures.create_product(api, sku="WIDGET-2", unit_price_cents=500, case_qty=12,
                                   case_price_cents=5400, pallet_case_qty=10, pallet_price_cents=48000,
                                   on_hand_qty=1000, par_level=200, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    line = validate_success(
        api.add_order_line(order["id"], {"product_id": prod["id"], "quantity": 12},
                           make_buyer_headers(acct["id"])), 201,
    )
    assert line["pricing_tier"] == "CASE"


def test_quantity_equal_to_case_qty_prices_as_one_case(api):
    """PRD §3.3: "The `line_subtotal_cents` is the number of full pallets times `pallet_price_cents`,
    plus the number of full cases times `case_price_cents`, plus the leftover eaches times
    `unit_price_cents`."

    Design: Difficulty/boundary_precision_check/line_qty_at_case_qty_selects_case_tier
    """
    acct = fixtures.create_account(api, credit_terms="PREPAID")
    prod = fixtures.create_product(api, sku="WIDGET-2b", unit_price_cents=500, case_qty=12,
                                   case_price_cents=5400, pallet_case_qty=10, pallet_price_cents=48000,
                                   on_hand_qty=1000, par_level=200, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    line = validate_success(
        api.add_order_line(order["id"], {"product_id": prod["id"], "quantity": 12},
                           make_buyer_headers(acct["id"])), 201,
    )
    assert line["line_subtotal_cents"] == 5400


# --------------------------------------------------------------------------- #
# calculations / line_qty_below_case_qty_selects_each_tier (corner)
# --------------------------------------------------------------------------- #
def test_quantity_below_case_qty_selects_each_tier(api):
    """PRD §3.3: "a quantity of exactly `case_qty` (with no full pallet) is one full case and
    prices as `CASE`, while a quantity of `case_qty` minus one is all eaches and prices as `EACH`."

    Design: Corner/calculations/line_qty_below_case_qty_selects_each_tier
    """
    acct = fixtures.create_account(api, credit_terms="PREPAID")
    prod = fixtures.create_product(api, sku="EA-1", unit_price_cents=500, case_qty=12,
                                   case_price_cents=5400, pallet_case_qty=10, pallet_price_cents=48000,
                                   on_hand_qty=1000, par_level=200, reorder_point=10)
    order = fixtures.create_order(api, acct["id"])
    line = validate_success(
        api.add_order_line(order["id"], {"product_id": prod["id"], "quantity": 11},
                           make_buyer_headers(acct["id"])), 201,
    )
    assert line["pricing_tier"] == "EACH"
    assert line["line_subtotal_cents"] == 5500


# --------------------------------------------------------------------------- #
# combinatorial_formula / order_tax_round_per_line_then_sum
# --------------------------------------------------------------------------- #
def _two_line_taxable_order(api):
    acct = fixtures.create_account(api, credit_terms="NET_15")
    pepper = fixtures.create_product(api, sku="PEPPER-1", taxable=True, unit_price_cents=630,
                                     case_qty=100, case_price_cents=60000, pallet_case_qty=10,
                                     pallet_price_cents=560000, par_level=50)
    salt = fixtures.create_product(api, sku="SALT-1", taxable=True, unit_price_cents=630,
                                   case_qty=100, case_price_cents=60000, pallet_case_qty=10,
                                   pallet_price_cents=560000, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], pepper["id"], 1)
    fixtures.add_line(api, order["id"], acct["id"], salt["id"], 1)
    return acct, order


def test_order_tax_rounds_each_line_before_summing(api):
    """PRD §3.4: "for each non-cancelled line whose product's `taxable` flag is true, multiply
    that line's `line_subtotal_cents` by the account's `tax_rate` and round the product to whole
    cents using round-half-up; the order's `tax_cents` is the sum of those per-line rounded amounts."

    Design: Difficulty/combinatorial_formula/order_tax_round_per_line_then_sum
    """
    acct, order = _two_line_taxable_order(api)
    confirmed = fixtures.confirm_order(api, order["id"], acct["id"])
    # 630*0.08 = 50.4 -> 50 per line; 50 + 50 = 100 (sum-then-round would give 101)
    assert confirmed["tax_cents"] == 100


def test_order_total_reflects_per_line_tax_sum(api):
    """PRD §2.5: "each line's figure is rounded to whole cents before any summation across lines;
    summing first and rounding once is explicitly not equivalent and must not be substituted."
    PRD §3.4: "`total_cents` (which is the merchandise subtotal plus tax plus freight)."

    Design: Difficulty/combinatorial_formula/order_tax_round_per_line_then_sum
    """
    acct, order = _two_line_taxable_order(api)
    confirmed = fixtures.confirm_order(api, order["id"], acct["id"])
    assert confirmed["merchandise_subtotal_cents"] == 1260
    assert confirmed["total_cents"] == 1360


# --------------------------------------------------------------------------- #
# calculations / certified_account_order_has_zero_tax (corner)
# --------------------------------------------------------------------------- #
def test_certified_account_order_has_zero_tax(api):
    """PRD §3.4: "If the owning account's `tax_exempt_status` is `CERTIFIED` at the moment tax is
    computed, the order's `tax_cents` is zero."

    Design: Corner/calculations/certified_account_order_has_zero_tax
    """
    acct, _cert = fixtures.approved_certificate_account(api)
    prod = fixtures.create_product(api, sku="TF-1", taxable=True, unit_price_cents=1000,
                                   case_qty=100, case_price_cents=90000, pallet_case_qty=10,
                                   pallet_price_cents=850000, weight_lbs_per_unit=2, par_level=50)
    order = fixtures.create_order(api, acct["id"])
    fixtures.add_line(api, order["id"], acct["id"], prod["id"], 5)
    confirmed = fixtures.confirm_order(api, order["id"], acct["id"])
    assert confirmed["tax_cents"] == 0
    assert confirmed["total_cents"] == 5000
