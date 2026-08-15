"""Bid-line pricing variants, per-line rounding discipline, and the bid roll-up."""
from test_helpers import (
    PM,
    ApiErrorId,
    add_base_work_item,
    award_project,
    create_draft_project,
    get_project,
    get_success_data,
    submit_bid,
    validate_error,
    validate_success,
)


class TestDualVariantLinePricing:
    def test_lump_sum_line_prices_quantity_times_unit_price(self, api):
        """PRD §3.2: "its priced value is the quantity multiplied by the unit
        price, rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/bid_line_pricing_lump_sum_vs_time_and_materials
        """
        project = create_draft_project()
        item = add_base_work_item(
            project["id"],
            description="Valve overhaul (lump)",
            trade_code="MACHINERY",
            pricing_mode="LUMP_SUM",
            duration_days=3,
            quantity=7.5,
            unit_price_cents=9500,
        )
        assert item["line_total_cents"] == 71250, (
            f"round_half_up(7.5 x 9500) = 71250, got {item['line_total_cents']}"
        )

    def test_time_and_materials_adds_marked_up_materials(self, api):
        """PRD §3.2: "its priced value is the estimated hours multiplied by the
        hourly rate, rounded half-up to a whole cent, plus the materials
        subtotal increased by a fifteen percent markup and itself rounded
        half-up to a whole cent."
        PRD §3.2: "Consequently, a time-and-materials line prices strictly
        higher than a lump-sum line of equivalent labour value whenever a
        nonzero materials subtotal is charged."

        Design: Difficulty/dual_variant_calc/bid_line_pricing_lump_sum_vs_time_and_materials
        """
        project = create_draft_project()
        lump = add_base_work_item(
            project["id"],
            description="Valve overhaul (lump)",
            trade_code="MACHINERY",
            pricing_mode="LUMP_SUM",
            duration_days=3,
            quantity=7.5,
            unit_price_cents=9500,
        )
        tm = add_base_work_item(
            project["id"],
            description="Valve overhaul (T&M)",
            trade_code="MACHINERY",
            pricing_mode="TIME_AND_MATERIALS",
            duration_days=3,
            estimated_hours=7.5,
            hourly_rate_cents=9500,
            materials_cost_cents=10000,
        )
        assert tm["line_total_cents"] == 82750, (
            f"71250 labour + round_half_up(10000 x 1.15) = 11500 materials = "
            f"82750, got {tm['line_total_cents']}"
        )
        assert tm["line_total_cents"] > lump["line_total_cents"], (
            "Identical labour inputs price strictly higher under "
            "TIME_AND_MATERIALS with a nonzero materials subtotal"
        )
        submit_bid(project["id"])
        project_after = get_project(project["id"])
        assert project_after["bid_total_cents"] == 154000, (
            f"Bid roll-up 71250 + 82750 = 154000, got "
            f"{project_after['bid_total_cents']}"
        )


class TestPerLineRoundingThenSum:
    def test_each_line_rounded_half_up_individually(self, api):
        """PRD §2.6: "Rounding is pinned to the line level: every priced line
        (a work item's `line_total_cents`, a change order's
        `proposed_cost_cents`, a reservation's `dockage_fee_cents`) is rounded
        half-up to a whole cent individually, and every total is a sum of
        already-rounded line values."

        Design: Difficulty/combinatorial_formula/bid_subtotal_per_line_rounding_then_sum
        """
        project = create_draft_project()
        line_a = add_base_work_item(
            project["id"], description="Blast zone A", trade_code="COATINGS",
            duration_days=2, quantity=1.008, unit_price_cents=550,
        )
        line_b = add_base_work_item(
            project["id"], description="Blast zone B", trade_code="COATINGS",
            duration_days=2, quantity=1.008, unit_price_cents=550,
        )
        assert line_a["line_total_cents"] == 554, (
            f"round_half_up(1.008 x 550 = 554.4) = 554, got "
            f"{line_a['line_total_cents']}"
        )
        assert line_b["line_total_cents"] == 554

    def test_bid_total_sums_rounded_lines_not_raw_products(self, api):
        """PRD §2.6: "Summing unrounded products and rounding once at the end
        is a rejected alternative, because it can yield a different cent."

        Design: Difficulty/combinatorial_formula/bid_subtotal_per_line_rounding_then_sum
        """
        project = create_draft_project()
        add_base_work_item(
            project["id"], description="Blast zone A", trade_code="COATINGS",
            duration_days=2, quantity=1.008, unit_price_cents=550,
        )
        add_base_work_item(
            project["id"], description="Blast zone B", trade_code="COATINGS",
            duration_days=2, quantity=1.008, unit_price_cents=550,
        )
        submitted = submit_bid(project["id"])
        assert submitted["bid_total_cents"] == 1108, (
            f"554 + 554 = 1108 (sum-then-round would yield 1109), got "
            f"{submitted['bid_total_cents']}"
        )


class TestBidRollupInputSet:
    def test_bid_total_excludes_cancelled_items(self, api):
        """PRD §3.2: "The project's `bid_total_cents` is a live roll-up: the
        sum of `line_total_cents` across its work items whose `origin_kind` is
        `BASE_SPEC` and whose status is anything but `CANCELLED`."

        Design: Corner/calculations/bid_total_excludes_cancelled_items
        """
        project = create_draft_project()
        add_base_work_item(
            project["id"], description="Line X", quantity=1, unit_price_cents=10000
        )
        line_y = add_base_work_item(
            project["id"], description="Line Y", quantity=1, unit_price_cents=20000
        )
        get_success_data(api.cancel_work_item(line_y["id"], PM))
        submitted = submit_bid(project["id"])
        assert submitted["bid_total_cents"] == 10000, (
            f"Cancelled 20000-cent line excluded from the roll-up, got "
            f"{submitted['bid_total_cents']}"
        )

    def test_submit_bid_without_items_returns_bid_empty(self, api):
        """PRD §3.2: "Submission requires at least one non-cancelled
        `BASE_SPEC` line — an empty specification is rejected with
        `ERR_BID_EMPTY`"

        Design: Corner/errors/submit_bid_without_items_returns_bid_empty
        """
        project = create_draft_project()
        resp = api.submit_bid(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_BID_EMPTY)


class TestAwardConsistency:
    def test_award_response_reflects_contracted_price_immediately(self, api):
        """PRD §3.3: "The current `bid_total_cents` is snapshot into
        `awarded_price_cents`; `contracted_price_cents` — null, like the
        awarded figure, until this moment — initialises to the awarded figure;
        `ld_daily_rate_cents` is selected from the liquidated-damages tier
        table of §3.7 against the contracted price"
        PRD §3.7: "A contracted price below 50000000 cents (that is,
        $500,000.00) selects a rate of 200000 cents per day ($2,000.00)."

        Design: Corner/consistency_model/award_response_reflects_contracted_price_immediately
        """
        project = create_draft_project()
        add_base_work_item(
            project["id"], description="Valve overhaul (lump)",
            trade_code="MACHINERY", duration_days=3, quantity=7.5,
            unit_price_cents=9500,
        )
        add_base_work_item(
            project["id"], description="Valve overhaul (T&M)",
            trade_code="MACHINERY", pricing_mode="TIME_AND_MATERIALS",
            duration_days=3, estimated_hours=7.5, hourly_rate_cents=9500,
            materials_cost_cents=10000,
        )
        submit_bid(project["id"])
        awarded = award_project(project["id"])
        assert awarded["status"] == "CONTRACTED"
        assert awarded["awarded_price_cents"] == 154000
        assert awarded["contracted_price_cents"] == 154000, (
            "The award response body itself carries the initialised contracted "
            "price — no re-read required"
        )
        assert awarded["ld_daily_rate_cents"] == 200000, (
            f"154000 < 50000000 selects tier 1 (200000/day), got "
            f"{awarded['ld_daily_rate_cents']}"
        )
