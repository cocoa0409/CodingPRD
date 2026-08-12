"""PO line pricing: cooperative tier schedules vs flat pins, marginal
allocation across tier breakpoints, and drawdown guards (PRD §3.4)."""
from test_helpers import (
    ApiErrorId, STANDARD_TIER_TABLE, TWO_TIER_TABLE,
    make_district_buyer_headers, validate_error, validate_paginated,
    validate_success, accept_po, add_po_line, build_accepted_award_context,
    cancel_po_line, create_po, get_po,
)


def _buyer(ctx):
    return make_district_buyer_headers(ctx["district"]["id"])


class TestPricingVariantDivergence:
    def test_coop_tiered_line_prices_off_tier_schedule(self, api):
        """PRD §3.4: "each unit's price is the `unit_price_cents` of the tier row
        with the greatest `min_qty` that the unit's position has reached or passed."
        PRD §3.4: "The line's `line_total_cents` is the exact integer-cent sum of
        those per-unit prices"

        Design: Difficulty/dual_variant_calc/poline_pricing_coop_tiered_vs_award_flat_divergence
        """
        ctx = build_accepted_award_context(
            pricing_mode="COOP_TIERED", tier_table=STANDARD_TIER_TABLE,
            with_site=False, with_crew=False)
        po = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-A1")
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 20},
            _buyer(ctx)), 201)
        # Cumulative base 0: units 1..20 all sit below min_qty 100 -> tier 1.
        assert line["line_total_cents"] == 240000
        assert line["computed_unit_price_cents"] == 12000
        assert line["coop_agreement_id"] == ctx["coop"]["id"]

    def test_award_flat_line_prices_pinned_flat_and_diverges(self, api):
        """PRD §3.4: "Under `AWARD_FLAT`, every unit carries the pinned
        `flat_unit_price_cents`: `computed_unit_price_cents` equals it exactly, and
        `line_total_cents` is `ordered_qty` multiplied by it."
        PRD §3.4: "whenever the flat price sits below the first tier or a tier
        boundary is crossed, the tiered variant yields the higher total."

        Design: Difficulty/dual_variant_calc/poline_pricing_coop_tiered_vs_award_flat_divergence
        """
        ctx = build_accepted_award_context(
            pricing_mode="AWARD_FLAT", flat_unit_price_cents=11000,
            with_site=False, with_crew=False)
        po = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-B1")
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 20},
            _buyer(ctx)), 201)
        assert line["line_total_cents"] == 220000
        assert line["computed_unit_price_cents"] == 11000
        # Identical qty and spec economics priced 240000 under COOP_TIERED.
        assert line["line_total_cents"] != 240000


class TestMarginalTierAllocation:
    def _setup_base_90(self, api):
        ctx = build_accepted_award_context(
            pricing_mode="COOP_TIERED", tier_table=TWO_TIER_TABLE,
            with_site=False, with_crew=False)
        po1 = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-1")
        add_po_line(po1["id"], ctx["spec_line"]["id"], ctx["district"]["id"], 90)
        po2 = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-2")
        return ctx, po2

    def test_coop_marginal_allocation_straddles_tier_breakpoint(self, api):
        """PRD §3.4: "The new line's units are then priced one at a time, the first
        unit occupying cumulative position one past that base and each subsequent
        unit advancing the position by one; each unit's price is the
        `unit_price_cents` of the tier row with the greatest `min_qty` that the
        unit's position has reached or passed."

        Design: Difficulty/combinatorial_formula/coop_marginal_tier_allocation_straddling_breakpoint
        """
        ctx, po2 = self._setup_base_90(api)
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po2["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 20},
            _buyer(ctx)), 201)
        # Units 91..99 at 12000 (= 108000); units 100..110 at 10500 (= 115500).
        assert line["line_total_cents"] == 223500

    def test_straddling_line_unit_price_is_rounded_half_up(self, api):
        """PRD §3.4: "its `computed_unit_price_cents` is that total divided by
        `ordered_qty`, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/coop_marginal_tier_allocation_straddling_breakpoint
        """
        ctx, po2 = self._setup_base_90(api)
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po2["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 20},
            _buyer(ctx)), 201)
        assert line["computed_unit_price_cents"] == 11175  # round_half_up(223500 / 20)
        # Neither the naive all-tier-1 (240000) nor all-tier-2 (210000) reading.
        assert line["line_total_cents"] not in (240000, 210000)


class TestCoopTierBoundary:
    def _setup_base_90(self, api):
        ctx = build_accepted_award_context(
            pricing_mode="COOP_TIERED", tier_table=TWO_TIER_TABLE,
            with_site=False, with_crew=False)
        po1 = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-1")
        add_po_line(po1["id"], ctx["spec_line"]["id"], ctx["district"]["id"], 90)
        po2 = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-2")
        return ctx, po2

    def test_hundredth_unit_prices_at_tier_two(self, api):
        """PRD §3.4: "each unit's price is the `unit_price_cents` of the tier row
        with the greatest `min_qty` that the unit's position has reached or passed."

        Design: Difficulty/boundary_precision_check/coop_tier_boundary_exactly_100th_unit_prices_tier2
        """
        ctx, po2 = self._setup_base_90(api)
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po2["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 10},
            _buyer(ctx)), 201)
        # Units 91..99 at 12000 (= 108000); unit 100 has reached min_qty 100 -> 10500.
        assert line["line_total_cents"] == 118500

    def test_hundredth_unit_total_excludes_naive_readings(self, api):
        """PRD §3.4: "a row applies to a cumulative unit position that has reached
        or passed its `min_qty`." (§3.1)
        PRD §3.4: "its `computed_unit_price_cents` is that total divided by
        `ordered_qty`, rounded half-up to whole cents."

        Design: Difficulty/boundary_precision_check/coop_tier_boundary_exactly_100th_unit_prices_tier2
        """
        ctx, po2 = self._setup_base_90(api)
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po2["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 10},
            _buyer(ctx)), 201)
        assert line["computed_unit_price_cents"] == 11850  # round_half_up(118500 / 10)
        assert line["line_total_cents"] != 120000  # a '>' boundary reading
        assert line["line_total_cents"] != 105000  # an all-tier-2 reading


class TestComputedFieldsAndInputSet:
    def test_poline_computed_unit_price_client_input_ignored(self, api):
        """PRD §3.4: "client-supplied values for computed fields such as
        `computed_unit_price_cents` are ignored."

        Design: Corner/entities/poline_computed_unit_price_client_input_ignored
        """
        ctx = build_accepted_award_context(
            pricing_mode="COOP_TIERED", tier_table=TWO_TIER_TABLE,
            with_site=False, with_crew=False)
        po = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-1")
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"],
             "ordered_qty": 3, "computed_unit_price_cents": 1},
            _buyer(ctx)), 201)
        assert line["computed_unit_price_cents"] == 12000
        assert line["line_total_cents"] == 36000

    def test_ytd_volume_excludes_cancelled_lines(self, api):
        """PRD §3.4: "the sum of `ordered_qty` across every non-`CANCELLED` line
        that references the same cooperative agreement, sits on a purchase order of
        the same district, and whose purchase order's `fiscal_year` equals the
        agreement's `contract_year`, evaluated in line-creation order (`created_at`
        ascending)"

        Design: Corner/calculations/ytd_volume_excludes_cancelled_lines
        """
        ctx = build_accepted_award_context(
            pricing_mode="COOP_TIERED", tier_table=TWO_TIER_TABLE,
            with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        po1 = create_po(ctx["award"]["id"], d_id, po_number="PO-1")
        add_po_line(po1["id"], ctx["spec_line"]["id"], d_id, 90)
        po2 = create_po(ctx["award"]["id"], d_id, po_number="PO-2")
        cancelled = add_po_line(po2["id"], ctx["spec_line"]["id"], d_id, 50)
        cancel_po_line(cancelled["id"], d_id)
        po3 = create_po(ctx["award"]["id"], d_id, po_number="PO-3")

        line = validate_success(api.create_po_line(
            {"purchase_order_id": po3["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 20},
            _buyer(ctx)), 201)
        # Base is 90, not 140: units 91..99 at 12000, units 100..110 at 10500.
        assert line["line_total_cents"] == 223500
        assert line["line_total_cents"] != 210000

    def test_poline_qty_over_remaining_returns_award_qty_exceeded(self, api):
        """PRD §3.4: "the drawdown must fit — `ordered_qty` no greater than the
        spec line's `remaining_qty` (`ERR_AWARD_QTY_EXCEEDED`)"

        Design: Corner/errors/poline_qty_over_remaining_returns_award_qty_exceeded
        """
        ctx = build_accepted_award_context(with_site=False, with_crew=False)
        po = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-1")
        resp = api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 501},
            _buyer(ctx))
        validate_error(resp, ApiErrorId.ERR_AWARD_QTY_EXCEEDED)

    def test_immediate_consistency_poline_totals_visible_on_po_read(self, api):
        """PRD §3.4: "At creation the line ... debits the spec line's
        `remaining_qty` by `ordered_qty`, and triggers recompute of the order's
        `total_cents` — the sum of `line_total_cents` over the order's
        non-`CANCELLED` lines."

        Design: Corner/consistency_model/immediate_consistency_poline_totals_visible_on_po_read
        """
        ctx = build_accepted_award_context(with_site=False, with_crew=False)
        po = create_po(ctx["award"]["id"], ctx["district"]["id"], po_number="PO-1")
        assert po["total_cents"] == 0
        line = validate_success(api.create_po_line(
            {"purchase_order_id": po["id"], "spec_line_id": ctx["spec_line"]["id"], "ordered_qty": 7},
            _buyer(ctx)), 201)
        assert line["line_total_cents"] == 77000
        assert get_po(po["id"])["total_cents"] == 77000


class TestPOLineListing:
    def test_list_polines_paginates_and_filters_by_po(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
        PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
        `total_count`, `has_more`) are included for list endpoints."

        Design: Corner/endpoints/list_polines_paginates_and_filters_by_po
        """
        ctx = build_accepted_award_context(with_site=False, with_crew=False)
        d_id = ctx["district"]["id"]
        po1 = create_po(ctx["award"]["id"], d_id, po_number="PO-1")
        for _ in range(3):
            add_po_line(po1["id"], ctx["spec_line"]["id"], d_id, 3)
        po2 = create_po(ctx["award"]["id"], d_id, po_number="PO-2")
        add_po_line(po2["id"], ctx["spec_line"]["id"], d_id, 7)

        page1, meta1 = validate_paginated(api.list_po_lines(
            _buyer(ctx), params={"purchase_order_id": po1["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3 and meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_po_lines(
            _buyer(ctx), params={"purchase_order_id": po1["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["has_more"] is False

        seen = {l["id"] for l in page1} | {l["id"] for l in page2}
        assert page1[0]["id"] != page2[0]["id"]
        assert all(l["purchase_order_id"] == po1["id"] for l in page1 + page2)
        assert len(seen) == 3
