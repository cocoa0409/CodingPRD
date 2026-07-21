"""Pricing and order-total calculations (PRD §2.6, §3.5).

Covers wholesale volume-tier selection, round-per-line-then-sum precision, the
50-unit tier boundary, the gift-wrap fee, and immediate visibility of computed
totals.
"""
from test_helpers import (
    validate_success, make_customer_headers,
    create_customer, create_product, create_order, add_line, confirm_order,
    setup_confirmed_retail_order,
)


class TestWholesaleTierCombinatorial:
    """combinatorial_formula / wholesale_tier_selection_three_inputs — a
    wholesale unit price is a non-linear function of base price, account type,
    and total order units (120 -> 10% tier)."""

    def _confirm_ws_120(self):
        customer = create_customer(account_type="WHOLESALE", credit_limit_cents=20000000)
        product = create_product(base_price_cents=1000, shelf_life_days=90, unit_weight_g=100)
        order = create_order(customer["id"], "WHOLESALE")
        add_line(order["id"], customer["id"], product["id"], 120)
        return confirm_order(order["id"], customer["id"])

    def test_wholesale_120_units_tier_subtotal(self):
        """PRD §3.5: "when it is at least 50 units (but under 200) it is 0.10".
        PRD §3.5: "Each wholesale line's `unit_price_cents` is the product's base
        price multiplied by one minus the applicable tier fraction, again
        retained at fractional precision."

        Design: Difficulty/combinatorial_formula/wholesale_tier_selection_three_inputs
        """
        order = self._confirm_ws_120()
        # 1000 * (1 - 0.10) = 900 per unit; line_total = round(900*120) = 108000.
        assert order["subtotal_cents"] == 108000, order

    def test_wholesale_120_units_tax_and_total(self):
        """PRD §3.5: "Tax, `tax_cents`, is the subtotal multiplied by the tax
        rate of 0.0725, rounded half up to whole cents." PRD §3.5: "The order's
        `total_cents` is the subtotal plus tax plus gift fee, minus the wallet
        amount applied."

        Design: Difficulty/combinatorial_formula/wholesale_tier_selection_three_inputs
        """
        order = self._confirm_ws_120()
        assert order["tax_cents"] == 7830, order
        assert order["total_cents"] == 115830, order


class TestRoundPerLineThenSum:
    """combinatorial_formula / order_total_round_per_line_then_sum — two retail
    lines at unit_exact 959.5 round to 960 each (round-per-line-then-sum)."""

    def _confirm_two_line_retail(self):
        customer = create_customer(account_type="RETAIL", loyalty_discount_pct=0.05)
        px = create_product(base_price_cents=1010, shelf_life_days=30, unit_weight_g=20)
        py = create_product(base_price_cents=1010, shelf_life_days=30, unit_weight_g=20)
        order = create_order(customer["id"], "RETAIL")
        add_line(order["id"], customer["id"], px["id"], 1)
        add_line(order["id"], customer["id"], py["id"], 1)
        return confirm_order(order["id"], customer["id"])

    def test_round_per_line_subtotal(self):
        """PRD §2.6: "The authoritative rounding discipline for order subtotals is
        round-per-line-then-sum — each line is rounded to whole cents first, and
        the subtotal is the sum of those already-rounded line totals, never the
        rounded sum of exact line amounts."

        Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum
        """
        order = self._confirm_two_line_retail()
        # 1010*0.95 = 959.5 -> round half up -> 960 per line; 960+960 = 1920
        # (sum-then-round would give 1919). The pinned order is decisive.
        assert order["subtotal_cents"] == 1920, order

    def test_round_per_line_tax_and_total(self):
        """PRD §3.5: "Each line's `line_total_cents` is the line's
        `unit_price_cents` multiplied by its `quantity`, rounded half up to whole
        cents." PRD §3.5: "Tax, `tax_cents`, is the subtotal multiplied by the
        tax rate of 0.0725, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/order_total_round_per_line_then_sum
        """
        order = self._confirm_two_line_retail()
        assert order["tax_cents"] == 139, order
        assert order["total_cents"] == 2059, order


class TestWholesaleTierBoundary:
    """boundary_precision_check / wholesale_tier_boundary_exactly_50 — the >=
    boundary on total order units: exactly 50 units triggers the 10% tier."""

    def _confirm_ws(self, qty):
        customer = create_customer(account_type="WHOLESALE", credit_limit_cents=20000000)
        product = create_product(base_price_cents=1000, shelf_life_days=90, unit_weight_g=100)
        order = create_order(customer["id"], "WHOLESALE")
        add_line(order["id"], customer["id"], product["id"], qty)
        return confirm_order(order["id"], customer["id"])

    def test_exactly_50_units_gets_ten_percent_tier(self):
        """PRD §3.5: "These boundaries are inclusive on the lower edge, so 49
        total units earn no discount while 50 total units earn the 0.10 tier."

        Design: Difficulty/boundary_precision_check/wholesale_tier_boundary_exactly_50
        """
        order = self._confirm_ws(50)
        # 1000*0.90 = 900; round(900*50) = 45000
        assert order["subtotal_cents"] == 45000, order
        assert order["tax_cents"] == 3263, order
        assert order["total_cents"] == 48263, order

    def test_forty_nine_units_below_boundary_no_discount(self):
        """PRD §3.5: "below 50 units there is no discount ... These boundaries are
        inclusive on the lower edge, so 49 total units earn no discount while 50
        total units earn the 0.10 tier."

        Design: Difficulty/boundary_precision_check/wholesale_tier_boundary_exactly_50
        """
        order = self._confirm_ws(49)
        # No discount: unit 1000; round(1000*49) = 49000.
        assert order["subtotal_cents"] == 49000, order


def test_gift_wrap_fee_added_to_total():
    """PRD §3.5: "The gift fee, `gift_fee_cents`, is 500 cents when `is_gift` is
    true and 0 otherwise." PRD §3.5: "The order's `total_cents` is the subtotal
    plus tax plus gift fee, minus the wallet amount applied."

    Design: Corner/calculations/gift_wrap_fee_added_to_total
    """
    setup = setup_confirmed_retail_order(line_qty=1, base_price=1000, is_gift=True)
    order = setup["order"]
    assert order["subtotal_cents"] == 1000, order
    assert order["tax_cents"] == 73, order
    assert order["gift_fee_cents"] == 500, order
    assert order["total_cents"] == 1573, order


def test_order_confirm_totals_visible_in_same_response(api):
    """PRD §3.5: "The order's `total_cents` is the subtotal plus tax plus gift
    fee, minus the wallet amount applied." PRD §2.2: "operations that create or
    modify a resource will return the created or updated resource object in the
    data field."

    Design: Corner/consistency_model/order_confirm_totals_visible_same_response
    """
    setup = setup_confirmed_retail_order(line_qty=2, base_price=1000)
    order = setup["order"]
    # base 1000, qty 2, no loyalty: subtotal 2000; tax round(145.0)=145; total 2145.
    assert order["subtotal_cents"] == 2000, order
    assert order["tax_cents"] == 145, order
    assert order["total_cents"] == 2145, order
    # Re-read confirms the same computed totals are persisted immediately.
    headers = make_customer_headers(setup["customer"]["id"])
    fetched = validate_success(api.get_order(order["id"], headers))
    assert fetched["total_cents"] == 2145, fetched
