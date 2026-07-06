"""Checkout settlement: order-subtotal pinned rounding order, final loyalty
accrual, and tax on a taxable line.

Difficulty-queue instances for subtotal and loyalty; one Corner/calculations
instance for tax.
"""
from test_helpers import fixtures, validate_success
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["store_clerk_headers"]


def _setup_two_spice_lines_final(api):
    """BASIC member, non-bulk Spice product (unit 67), two BYO containers, an
    order with two lines each filled to net 150 (raw 100.5 -> 101 per line).
    Returns dict(order, line_a, line_b)."""
    member = fixtures.create_member(api, tier="BASIC")
    product = fixtures.create_product(
        api, name="Spice", category="SPICES", unit_price_cents_per_100g=67,
        bulk_tier_threshold_g=100000, bulk_tier_price_cents_per_100g=67)
    station = fixtures.create_station(api)
    fixtures.create_bin(api, product_id=product["id"], station_id=station["id"],
                        reorder_threshold_g=100, last_recount_g=5000)
    ca = fixtures.create_container(api, declared_tare_g=200, member_id=member["id"])
    cb = fixtures.create_container(api, declared_tare_g=200, member_id=member["id"])
    order = fixtures.create_order(api, member_id=member["id"], station_id=station["id"])
    la = fixtures.add_line(api, order_id=order["id"], product_id=product["id"],
                           container_id=ca["id"], estimated_gross_g=350)
    lb = fixtures.add_line(api, order_id=order["id"], product_id=product["id"],
                           container_id=cb["id"], estimated_gross_g=350)
    fixtures.start_fill(api, order_id=order["id"])
    filled_a = fixtures.fill_line(api, line_id=la["id"], gross_weight_g=350, measured_tare_g=200)
    filled_b = fixtures.fill_line(api, line_id=lb["id"], gross_weight_g=350, measured_tare_g=200)
    return {"order": order, "line_a": filled_a, "line_b": filled_b}


class TestSubtotalRoundPerLineThenSum:
    """Two lines each rounding to 101c: the subtotal is the sum of already-rounded
    line prices (202), not a single rounding of the raw total (201)."""

    def test_each_spice_line_rounds_to_101(self, api):
        """PRD §2.5: "Line pricing rounds **per line**: each line's price is
        rounded to a whole cent before any order-level summation, and the order
        subtotal is the sum of those already-rounded line prices rather than a
        single rounding applied to the raw goods total."

        Design: Difficulty/combinatorial_formula/order_subtotal_round_per_line_then_sum
        """
        s = _setup_two_spice_lines_final(api)
        # net 150 -> 67 * 150 / 100 = 100.5 -> round half up -> 101 (per line).
        assert s["line_a"]["line_price_cents"] == 101
        assert s["line_b"]["line_price_cents"] == 101

    def test_order_subtotal_sums_rounded_lines(self, api):
        """PRD §3.6: "First, `subtotal_cents` is the sum of `line_price_cents`
        over the order's `FINAL`, non-voided lines — a sum of already-rounded line
        prices."
        PRD §3.6: "Fifth, `total_cents` equals `subtotal_cents` minus
        `discount_cents` plus `deposit_total_cents` plus `tax_cents`."

        Design: Difficulty/combinatorial_formula/order_subtotal_round_per_line_then_sum
        """
        s = _setup_two_spice_lines_final(api)
        order = fixtures.checkout_order(api, order_id=s["order"]["id"])
        assert order["subtotal_cents"] == 202, "101 + 101, round-per-line then sum"
        assert order["total_cents"] == 202


class TestFinalLoyaltyAccrual:
    """A PLUS member settling a 284c subtotal earns floor((284//100)*1.5)=3
    points, credited to the member's projected balance."""

    def test_checkout_reports_final_loyalty_earned(self, api):
        """PRD §3.6: "The base points are the settled amount divided by 100 (one
        base point per 100 cents, i.e., per dollar), taking the floor; at final
        checkout the settled amount is `subtotal_cents` minus `discount_cents`."
        PRD §3.6: "This final figure is recorded as the order's
        `loyalty_points_earned` and credited by a `LOYALTY_ACCRUAL` ledger entry
        whose `points_delta` is that value."

        Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_divergence
        """
        s = fixtures.setup_final_line(api, member_tier="PLUS", declared_tare_g=200,
                                      estimated_gross_g=1150,
                                      gross_weight_g=1250, measured_tare_g=200)
        order = fixtures.checkout_order(api, order_id=s["order"]["id"])
        assert order["subtotal_cents"] == 284
        assert order["loyalty_points_earned"] == 3

    def test_final_loyalty_credited_to_member_balance(self, api):
        """PRD §3.6: "Those base points are multiplied by a tier multiplier of 1.5
        for a `PLUS` member or 1.0 for a `BASIC` member, and the product is
        floored to a whole number."
        PRD §2.6: "`loyalty_points_balance` is the sum of all `points_delta`."

        Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_divergence
        """
        s = fixtures.setup_final_line(api, member_tier="PLUS", declared_tare_g=200,
                                      estimated_gross_g=1150,
                                      gross_weight_g=1250, measured_tare_g=200)
        fixtures.checkout_order(api, order_id=s["order"]["id"])
        member = validate_success(api.get_member(s["member"]["id"], CLERK), 200)
        assert member["loyalty_points_balance"] == 3


def test_taxable_line_applies_eight_percent_tax(api):
    """PRD §3.6: "The `tax_cents` is 8% of that taxable base, rounded half up to a
    whole cent, and is zero when the order has no taxable lines."
    PRD §3.6: "if the subtotal equals the taxable goods, the taxable base is the
    taxable goods minus the discount, floored at zero".

    Design: Corner/calculations/corner_order_tax_on_taxable_line
    """
    # BASIC, taxable product unit 100, net 100 -> goods 100 -> subtotal 100;
    # tax = round_half_up(0.08 * 100) = 8; total = 100 + 8 = 108.
    s = fixtures.setup_final_line(
        api, member_tier="BASIC", declared_tare_g=200, estimated_gross_g=300,
        gross_weight_g=300, measured_tare_g=200,
        product_overrides={"name": "SoapTaxable", "category": "CLEANING",
                           "unit_price_cents_per_100g": 100,
                           "bulk_tier_threshold_g": 100000,
                           "bulk_tier_price_cents_per_100g": 100, "taxable": True})
    order = fixtures.checkout_order(api, order_id=s["order"]["id"])
    assert order["subtotal_cents"] == 100
    assert order["tax_cents"] == 8
    assert order["total_cents"] == 108
