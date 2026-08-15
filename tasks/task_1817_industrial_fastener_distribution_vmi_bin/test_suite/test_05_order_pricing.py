"""Order pricing (PRD §3.4): UNIT_PRICE vs COST_PER_BIN variants, volume-tier
boundaries, truncating integer division, and the critical-part cert fee."""
from test_helpers import (
    TEST_USERS,
    create_agreement,
    create_cert,
    create_part,
    create_site,
    create_stop,
    create_route,
    get_success_data,
    setup_draft_order,
    setup_site_part_agreement,
    setup_started_route_with_stop,
    start_route,
    submit_stop,
)

ADMIN = TEST_USERS["admin_headers"]


def _order_fields(api, order_id):
    return get_success_data(api.get_replenishment_order(order_id, ADMIN))


class TestUnitPriceVsFlatBin:
    """Two agreements over the same part with identical counts: one priced
    UNIT_PRICE, one COST_PER_BIN (flat 7500). Both reorder points sit above
    the scanned count of 100 so the scan triggers an order of 500 pieces."""

    def _setup(self, api, is_critical=False, with_cert=False):
        ctx = setup_site_part_agreement(api, is_critical=is_critical,
                                        with_cert=with_cert,
                                        unit_price_cents=1000,
                                        total_stock_qty=100000,
                                        min_qty=150, max_qty=600,
                                        bin_location="A1")
        site, part = ctx["site"], ctx["part"]
        agr_b = create_agreement(api, site["id"], part["id"],
                                 bin_location="A2", pricing_mode="COST_PER_BIN",
                                 flat_bin_price_cents=7500,
                                 min_qty=150, max_qty=600)
        rs = setup_started_route_with_stop(api, site["id"],
                                           ctx["agreement"]["id"])
        stop_b = create_stop(api, rs["route"]["id"], agr_b["id"])
        return ctx, agr_b, rs["stop"], stop_b

    def test_unit_price_order_uses_tiered_quantity_pricing(self, api):
        """PRD §3.4: "Under `UNIT_PRICE` pricing, the base is the part's
        catalogue `unit_price_cents`, and a volume discount applies to it: when
        `ordered_qty` is at least 500 pieces, the applied unit price is the
        base times 95 divided by 100 — a five percent discount — computed with
        truncating integer division that discards any fractional cent".
        PRD §3.4: "The order's `total_price_cents` is that unit price
        multiplied by `ordered_qty`, and its `unit_price_cents` records the
        discounted unit."

        Count 100 on max 600 -> ordered 500 -> unit 950, total 475000.

        Design: Difficulty/dual_variant_calc/order_pricing_unit_vs_flat_bin_same_inputs
        """
        ctx, _agr_b, stop_u, _stop_b = self._setup(api)
        submitted = submit_stop(api, stop_u["id"], 100)
        order = _order_fields(api, submitted["generated_order_id"])
        assert order["ordered_qty"] == 500
        assert order["unit_price_cents"] == 950
        assert order["total_price_cents"] == 475000

    def test_cost_per_bin_order_uses_flat_per_trip_fee(self, api):
        """PRD §3.4: "Under `COST_PER_BIN` pricing, the order's
        `unit_price_cents` is zero and `total_price_cents` is simply the
        agreement's `flat_bin_price_cents` — a flat per-trip fee regardless of
        quantity."
        PRD §3.4: "The two modes price identically-inputted orders — same
        count, same part — differently whenever the flat fee differs from the
        discounted unit total, which is the normal case."

        Identical count 100 on max 600 -> ordered 500 -> unit 0, total 7500.

        Design: Difficulty/dual_variant_calc/order_pricing_unit_vs_flat_bin_same_inputs
        """
        _ctx, _agr_b, _stop_u, stop_b = self._setup(api)
        submitted = submit_stop(api, stop_b["id"], 100)
        order = _order_fields(api, submitted["generated_order_id"])
        assert order["ordered_qty"] == 500
        assert order["unit_price_cents"] == 0
        assert order["total_price_cents"] == 7500


class TestTierModeBranchAndCertFee:
    """Critical part (unit 1000) with a VALID certificate; identical scans of
    100 against min 150 / max 600 agreements in both pricing modes."""

    def _setup(self, api):
        site = create_site(api, credit_limit_cents=100000000)
        part = create_part(api, is_critical=True, unit_price_cents=1000,
                           total_stock_qty=100000)
        create_cert(api, part["id"], lot_number="LOT-1",
                    cert_expires_at="2027-01-01T00:00:00Z")
        agr_u = create_agreement(api, site["id"], part["id"],
                                 bin_location="C1", pricing_mode="UNIT_PRICE",
                                 min_qty=150, max_qty=600)
        agr_b = create_agreement(api, site["id"], part["id"],
                                 bin_location="C2", pricing_mode="COST_PER_BIN",
                                 flat_bin_price_cents=7500,
                                 min_qty=150, max_qty=600)
        route = create_route(api, site["id"])
        start_route(api, route["id"])
        stop_u = create_stop(api, route["id"], agr_u["id"])
        stop_b = create_stop(api, route["id"], agr_b["id"])
        return stop_u, stop_b

    def test_unit_price_critical_order_adds_cert_fee_after_tier(self, api):
        """PRD §3.4: "Pricing follows the agreement's `pricing_mode`, and the
        evaluation order is pinned: tier selection first, then quantity
        multiplication, then the certification fee."
        PRD §3.4: "In both modes, when the part `is_critical`, a flat
        certification handling fee of 1,500 cents is added to
        `total_price_cents`."

        950 x 500 + 1500 = 476500.

        Design: Difficulty/combinatorial_formula/order_pricing_tier_mode_branch_and_cert_fee
        """
        stop_u, _stop_b = self._setup(api)
        submitted = submit_stop(api, stop_u["id"], 100)
        order = _order_fields(api, submitted["generated_order_id"])
        assert order["unit_price_cents"] == 950
        assert order["total_price_cents"] == 476500, (
            "tier2 unit 950 x 500 pieces, then the 1500-cent cert fee"
        )

    def test_cost_per_bin_critical_order_bypasses_tier_logic(self, api):
        """PRD §3.4: "Under `COST_PER_BIN` pricing, the order's
        `unit_price_cents` is zero and `total_price_cents` is simply the
        agreement's `flat_bin_price_cents` — a flat per-trip fee regardless of
        quantity."
        PRD §3.4: "In both modes, when the part `is_critical`, a flat
        certification handling fee of 1,500 cents is added to
        `total_price_cents`."

        7500 flat + 1500 cert = 9000; quantity and tier are irrelevant.

        Design: Difficulty/combinatorial_formula/order_pricing_tier_mode_branch_and_cert_fee
        """
        _stop_u, stop_b = self._setup(api)
        submitted = submit_stop(api, stop_b["id"], 100)
        order = _order_fields(api, submitted["generated_order_id"])
        assert order["unit_price_cents"] == 0
        assert order["total_price_cents"] == 9000


class TestTierBoundariesAndPrecision:
    def test_tier1_boundary_at_exactly_100_pieces(self, api):
        """PRD §3.4: "when `ordered_qty` is at least 100 but below 500, the
        applied unit price is the base times 98 divided by 100, a two percent
        discount under the same truncating division; below 100 pieces the
        catalogue price applies undiscounted."

        Reorder points are set above the scanned counts so both scans trigger:
        count 100 on max 200 -> qty 100 -> unit 980, total 98000;
        count 9 on max 108 -> qty 99 -> unit 1000, total 99000.

        Design: Corner/calculations/order_pricing_tier1_boundary_at_exactly_100
        """
        site = create_site(api, ship_to_code="TB-1",
                           credit_limit_cents=100000000)
        part = create_part(api, sku="TB-P", unit_price_cents=1000,
                           total_stock_qty=100000)
        agr100 = create_agreement(api, site["id"], part["id"],
                                  bin_location="T100", min_qty=150,
                                  max_qty=200)
        agr99 = create_agreement(api, site["id"], part["id"],
                                 bin_location="T99", min_qty=10, max_qty=108)
        route = create_route(api, site["id"])
        start_route(api, route["id"])
        stop100 = create_stop(api, route["id"], agr100["id"])
        stop99 = create_stop(api, route["id"], agr99["id"])

        sub100 = submit_stop(api, stop100["id"], 100)
        order100 = _order_fields(api, sub100["generated_order_id"])
        assert order100["ordered_qty"] == 100
        assert order100["unit_price_cents"] == 980
        assert order100["total_price_cents"] == 98000, (
            ">= 100 pieces triggers the 2% tier"
        )

        sub99 = submit_stop(api, stop99["id"], 9)
        order99 = _order_fields(api, sub99["generated_order_id"])
        assert order99["ordered_qty"] == 99
        assert order99["unit_price_cents"] == 1000
        assert order99["total_price_cents"] == 99000, (
            "99 pieces stays undiscounted"
        )

    def test_tier_discount_uses_truncating_integer_division(self, api):
        """PRD §2.6: "Volume-tier discounts on catalogue prices are computed
        with truncating integer division, discarding any fractional cent toward
        zero."
        PRD §3.4: "when `ordered_qty` is at least 500 pieces, the applied unit
        price is the base times 95 divided by 100 — a five percent discount —
        computed with truncating integer division that discards any fractional
        cent".

        Base 999 at qty 500: 999 x 95 // 100 = 949 (not 949.05); total 474500.

        Design: Corner/calculations/order_pricing_integer_truncation_in_tier_discount
        """
        ctx = setup_draft_order(api, counted_qty=100, unit_price_cents=999,
                                min_qty=150, max_qty=600)
        order = _order_fields(api, ctx["order_id"])
        assert order["ordered_qty"] == 500
        assert order["unit_price_cents"] == 949
        assert order["total_price_cents"] == 474500
