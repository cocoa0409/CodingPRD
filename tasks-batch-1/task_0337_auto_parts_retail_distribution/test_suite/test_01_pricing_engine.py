"""Pricing engine: tiered net pricing, the retail-vs-wholesale variant split, the
margin-floor max branch, and round-then-multiply per-unit ordering.

Queue A: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_price_tier_payload, create_part_payload, create_account_payload,
    create_sales_order_payload, create_order_line_payload,
    TEST_USERS,
)

INV = TEST_USERS["inventory_manager_headers"]
REP = TEST_USERS["wholesale_rep_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]


def _tier(name, **kw):
    return get_success_data(api_client.create_price_tier(
        create_price_tier_payload(name=name, **kw), INV))


def _part(sku, **kw):
    return get_success_data(api_client.create_part(create_part_payload(sku=sku, **kw), INV))


def _account(name, account_type, tier_id, **kw):
    return get_success_data(api_client.create_account(
        create_account_payload(name=name, account_type=account_type,
                               price_tier_id=tier_id, **kw), REP))


def _order(account_id, channel, as_role):
    return get_success_data(api_client.create_sales_order(
        create_sales_order_payload(account_id, channel=channel), as_role))


# ─── dual_variant_calc: dvc_line_pricing_retail_vs_wholesale_on_part ──────────

class TestRetailVsWholesalePricing:
    """Same Part, two channels, two unit_merch_price_cents results."""

    def test_wholesale_line_prices_with_tier_discount(self, api):
        """PRD §3.3: "On a wholesale sale - an account of type WHOLESALE on the
        WHOLESALE channel - the full tier matrix applies, so both the discount and
        the margin floor bind and the same part yields a different
        unit_merch_price_cents than it would at retail."

        Wholesale caliper (list 20000, cost 9000) on JOBBER (discount 0.30, margin
        0.20): discounted = 14000, floor = ceil(9000*1.20) = 10800, max = 14000.

        Design: Difficulty/dual_variant_calc/dvc_line_pricing_retail_vs_wholesale_on_part
        """
        jobber = _tier("JOBBER", discount_pct=0.30, core_discount_pct=0.10, min_margin_pct=0.20)
        caliper = _part("CAL-100W", description="Brake caliper", list_price_cents=20000,
                        cost_cents=9000, core_charge_cents=6000, is_rebuildable=True,
                        warranty_days=90, stockable=True, reorder_point=1, reorder_qty=4)
        ws = _account("WS Shop", "WHOLESALE", jobber["id"], credit_limit_cents=1_000_000)
        order = _order(ws["id"], "WHOLESALE", REP)
        resp = api.create_order_line(create_order_line_payload(order["id"], caliper["id"], 1), REP)
        line = validate_success(resp, 201)
        assert line["unit_merch_price_cents"] == 14000, (
            f"wholesale unit_merch_price_cents expected 14000, got {line['unit_merch_price_cents']}"
        )

    def test_retail_line_prices_at_full_list(self, api):
        """PRD §3.3: "On a retail counter sale - an account of type RETAIL on the
        COUNTER channel - lines always price at full list: the merchandise discount
        is treated as zero and the margin floor never binds (list is at or above
        cost), so unit_merch_price_cents equals the part's list price regardless of
        the tier's discount."

        Same caliper on a RETAIL/COUNTER order prices at list 20000.

        Design: Difficulty/dual_variant_calc/dvc_line_pricing_retail_vs_wholesale_on_part
        """
        list_tier = _tier("LIST", discount_pct=0.00)
        caliper = _part("CAL-100R", description="Brake caliper", list_price_cents=20000,
                        cost_cents=9000, core_charge_cents=6000, is_rebuildable=True,
                        warranty_days=90, stockable=True, reorder_point=1, reorder_qty=4)
        rt = _account("Walk-in", "RETAIL", list_tier["id"])
        order = _order(rt["id"], "COUNTER", CLERK)
        resp = api.create_order_line(create_order_line_payload(order["id"], caliper["id"], 1), CLERK)
        line = validate_success(resp, 201)
        assert line["unit_merch_price_cents"] == 20000, (
            f"retail unit_merch_price_cents expected 20000 (full list), got "
            f"{line['unit_merch_price_cents']}"
        )

    def test_same_part_diverges_across_channels(self, api):
        """PRD §3.3: "the same part yields a different unit_merch_price_cents than
        it would at retail."

        The wholesale (14000) and retail (20000) prices for the identical part must
        differ.

        Design: Difficulty/dual_variant_calc/dvc_line_pricing_retail_vs_wholesale_on_part
        """
        jobber = _tier("JOBBER", discount_pct=0.30, core_discount_pct=0.10, min_margin_pct=0.20)
        list_tier = _tier("LIST", discount_pct=0.00)
        caliper = _part("CAL-100D", description="Brake caliper", list_price_cents=20000,
                        cost_cents=9000, core_charge_cents=6000, is_rebuildable=True,
                        warranty_days=90, stockable=True, reorder_point=1, reorder_qty=4)
        ws = _account("WS Shop", "WHOLESALE", jobber["id"], credit_limit_cents=1_000_000)
        rt = _account("Walk-in", "RETAIL", list_tier["id"])
        ws_order = _order(ws["id"], "WHOLESALE", REP)
        rt_order = _order(rt["id"], "COUNTER", CLERK)
        ws_line = validate_success(
            api.create_order_line(create_order_line_payload(ws_order["id"], caliper["id"], 1), REP), 201)
        rt_line = validate_success(
            api.create_order_line(create_order_line_payload(rt_order["id"], caliper["id"], 1), CLERK), 201)
        assert ws_line["unit_merch_price_cents"] == 14000
        assert rt_line["unit_merch_price_cents"] == 20000
        assert ws_line["unit_merch_price_cents"] != rt_line["unit_merch_price_cents"], (
            "wholesale and retail prices for the same part must diverge"
        )


# ─── combinatorial_formula: cf_margin_floor_max_branch_binds ──────────────────

class TestMarginFloorBranch:
    """The max(discounted, margin_floor) branch where the floor wins."""

    def test_margin_floor_wins_over_discounted(self, api):
        """PRD §3.3: "the net per-unit merchandise price unit_merch_price_cents is
        the greater of the discounted price and the margin floor - the floor
        protects against selling below the cost-plus-margin minimum."
        PRD §2.5: "the margin floor is rounded up to the next whole cent (so the
        floor can never be undercut by rounding)."

        DEEP tier (discount 0.50, margin 0.20), thin part list 1000 cost 900:
        discounted = 500, margin_floor = ceil(900*1.20) = 1080, max -> 1080.

        Design: Difficulty/combinatorial_formula/cf_margin_floor_max_branch_binds
        """
        deep = _tier("DEEP", discount_pct=0.50, core_discount_pct=0.00, min_margin_pct=0.20)
        part = _part("FLT-1", description="Oil filter", list_price_cents=1000, cost_cents=900,
                     core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                     stockable=True, reorder_point=0, reorder_qty=0)
        acct = _account("WS Deep", "WHOLESALE", deep["id"], credit_limit_cents=1_000_000)
        order = _order(acct["id"], "WHOLESALE", REP)
        line = validate_success(
            api.create_order_line(create_order_line_payload(order["id"], part["id"], 1), REP), 201)
        assert line["unit_merch_price_cents"] == 1080, (
            f"margin floor should bind at 1080, got {line['unit_merch_price_cents']}"
        )

    def test_margin_floor_branch_is_not_the_discounted_price(self, api):
        """PRD §3.3: "the net per-unit merchandise price unit_merch_price_cents is
        the greater of the discounted price and the margin floor - the floor
        protects against selling below the cost-plus-margin minimum."

        With discounted = 500 the result must not be the discounted figure; the
        floor (1080) is the larger of the two and therefore wins.

        Design: Difficulty/combinatorial_formula/cf_margin_floor_max_branch_binds
        """
        deep = _tier("DEEP2", discount_pct=0.50, core_discount_pct=0.00, min_margin_pct=0.20)
        part = _part("FLT-2", description="Oil filter", list_price_cents=1000, cost_cents=900,
                     core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                     stockable=True, reorder_point=0, reorder_qty=0)
        acct = _account("WS Deep2", "WHOLESALE", deep["id"], credit_limit_cents=1_000_000)
        order = _order(acct["id"], "WHOLESALE", REP)
        line = validate_success(
            api.create_order_line(create_order_line_payload(order["id"], part["id"], 1), REP), 201)
        assert line["unit_merch_price_cents"] != 500, "the discounted 500 must be overridden by the floor"
        assert line["unit_merch_price_cents"] == 1080


# ─── combinatorial_formula: cf_round_then_multiply_per_unit_order ─────────────

class TestRoundThenMultiply:
    """Per-unit rounding before multiplying by qty."""

    def test_per_unit_rounds_half_up_before_qty(self, api):
        """PRD §2.5: "Rounding is always applied to the per-unit figure first, and
        only then is the rounded per-unit amount multiplied by the line quantity -
        the system rounds-then-multiplies, never multiplies-then-rounds."

        HALF tier (discount 0.50), list 999: discounted = 499.5 -> round-half-up
        per unit -> 500.

        Design: Difficulty/combinatorial_formula/cf_round_then_multiply_per_unit_order
        """
        half = _tier("HALF", discount_pct=0.50, core_discount_pct=0.00, min_margin_pct=0.00)
        part = _part("PLG-9", description="Spark plug", list_price_cents=999, cost_cents=100,
                     core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                     stockable=True, reorder_point=0, reorder_qty=0)
        acct = _account("WS Half", "WHOLESALE", half["id"], credit_limit_cents=1_000_000)
        order = _order(acct["id"], "WHOLESALE", REP)
        line = validate_success(
            api.create_order_line(create_order_line_payload(order["id"], part["id"], 3), REP), 201)
        assert line["unit_merch_price_cents"] == 500, (
            f"unit price expected 500 (499.5 rounded half-up), got {line['unit_merch_price_cents']}"
        )

    def test_line_total_is_rounded_unit_times_qty(self, api):
        """PRD §3.3: "the line's extended totals are the per-unit figures multiplied
        by quantity: line_merch_total_cents is unit_merch_price_cents times qty".
        PRD §2.5: "The per-unit rounding in the first and fourth steps happens before
        the multiplication in the last step."

        500 (rounded per unit) * 3 = 1500 (not 999*3*0.5 = 1499 from multiply-then-round).

        Design: Difficulty/combinatorial_formula/cf_round_then_multiply_per_unit_order
        """
        half = _tier("HALF2", discount_pct=0.50, core_discount_pct=0.00, min_margin_pct=0.00)
        part = _part("PLG-10", description="Spark plug", list_price_cents=999, cost_cents=100,
                     core_charge_cents=0, is_rebuildable=False, warranty_days=30,
                     stockable=True, reorder_point=0, reorder_qty=0)
        acct = _account("WS Half2", "WHOLESALE", half["id"], credit_limit_cents=1_000_000)
        order = _order(acct["id"], "WHOLESALE", REP)
        line = validate_success(
            api.create_order_line(create_order_line_payload(order["id"], part["id"], 3), REP), 201)
        assert line["unit_merch_price_cents"] == 500
        assert line["line_merch_total_cents"] == 1500, (
            f"line total expected 1500 (round-then-multiply), got {line['line_merch_total_cents']}"
        )
