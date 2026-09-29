"""Calculation breadth: the score penalties, the peak-month and volume-discount stack, the
liquidation recovery ceiling, the billing run's utilization downgrade, the reimbursement
per-unit cap, headroom clipping, the zero-velocity risk flag and the FIFO draw order."""
import pytest

from test_helpers import (
    add_line_item,
    complete_removal,
    confirm_plan,
    create_forecast,
    create_in_transit_plan,
    create_listing,
    create_plan,
    decide_claim,
    file_claim,
    lots_for_listing,
    newest_quota,
    open_quota,
    place_multi_channel_order,
    read_claim,
    read_listing,
    read_lot,
    read_quota,
    read_removal_order,
    read_seller,
    receive_plan,
    register_fulfillment_center,
    register_seller,
    request_removal,
    run_storage_billing,
    set_clock,
    setup_baseline,
    setup_lot_with_split_pools,
    setup_received_lot,
    ship_plan,
)

STANDARD_TIER_METRICS = {
    "base_capacity_units": 1000,
    "sell_through_rate": 1.2500,
    "excess_units_ratio": 0.1500,
    "stranded_ratio": 0.0500,
    "in_stock_rate": 0.8000,
}


class TestIprsPenaltyStack:
    """Only the penalty that is actually earned applies, and it decides suspension."""

    def test_the_stranded_penalty_alone_drops_the_seller_below_the_floor(self):
        """The raw score is 217; the stranded ratio of 0.1000 earns the 75-point penalty
        while a clean discrepancy ledger avoids the 50-point one, leaving 142.

        PRD 3.1: "Those four weighted components are summed and the sum is multiplied by
        1000; the result is rounded half up to an integer."
        PRD 3.1: "A stranded penalty of 75 points applies when the period's `stranded_ratio`
        is strictly greater than 0.05. A discrepancy penalty of 50 points applies when the
        owning seller's `open_discrepancy_units` is strictly greater than 500 units."

        Design: Corner/calculations/iprs_penalty_stack_drops_seller_below_suspension_floor
        """
        set_clock("2026-08-01T00:00:00Z")
        seller = register_seller()
        assert seller["open_discrepancy_units"] == 0

        quota = open_quota(
            seller["id"], base_capacity_units=1000, sell_through_rate=0.0000,
            excess_units_ratio=0.0400, stranded_ratio=0.1000, in_stock_rate=0.0000,
        )
        assert quota["iprs_score"] == 142

    def test_a_score_below_two_hundred_restricts_the_tier_and_suspends_the_seller(self):
        """142 is below the 500 tier floor and below the 200 suspension floor, so the limit
        halves the base capacity and the account goes dark.

        PRD 3.1: "The effective tier selects a multiplier — 3.0 for `TIER_ELEVATED`, 1.5 for
        `TIER_STANDARD`, 0.5 for `TIER_RESTRICTED` — and `restock_limit_units` is the floor
        of `base_capacity_units` multiplied by that multiplier."
        PRD 3.1: "Scoring also has an account-level consequence: whenever the score is
        (re)computed, the owning seller's `seller_status` is set to `SUSPENDED` if the
        resulting `iprs_score` is strictly below 200, and to `ACTIVE` otherwise."

        Design: Corner/calculations/iprs_penalty_stack_drops_seller_below_suspension_floor
        """
        set_clock("2026-08-01T00:00:00Z")
        seller = register_seller()
        quota = open_quota(
            seller["id"], base_capacity_units=1000, sell_through_rate=0.0000,
            excess_units_ratio=0.0400, stranded_ratio=0.1000, in_stock_rate=0.0000,
        )
        assert quota["capacity_tier"] == "TIER_RESTRICTED"
        assert quota["restock_limit_units"] == 500
        assert quota["status"] == "ACTIVE"
        assert quota["utilized_units"] == 0
        assert read_seller(seller["id"])["seller_status"] == "SUSPENDED"


class TestMcfPeakSurchargeAndDiscountTier:
    """A December order whose surcharge is what pushes it over the 3% discount threshold."""

    def _fifty_units_in_stock_in_december(self) -> dict:
        ctx = setup_received_lot(units=50)
        set_clock("2026-12-05T00:00:00Z")
        return ctx

    def test_the_peak_surcharge_lifts_the_quote_into_the_three_percent_tier(self):
        """19000 gross plus a 1520 peak surcharge is 20520 pre-discount, which clears 20000
        and earns a 616-cent discount for a 19904-cent fee that still beats self-shipping.

        PRD 3.7: "`is_peak_period` is true when the calendar month of the logical clock at
        creation time is October, November or December, and when it is true a peak surcharge
        of eight percent of the gross fee, rounded half up, is added; otherwise the surcharge
        is zero."
        PRD 3.7: "The volume discount tier is keyed on that **pre-discount** total and never
        on the discounted figure: ten percent when the pre-discount total is at least 100000
        cents, six percent when it is at least 50000 cents, three percent when it is at least
        20000 cents, and zero otherwise."

        Design: Corner/calculations/mcf_peak_month_surcharge_and_three_percent_tier_flip_channel_choice
        """
        ctx = self._fifty_units_in_stock_in_december()
        order = place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 50, 1.00, "ZONE_1", "MCF", 20000
        )
        assert order["is_peak_period"] is True
        assert order["mcf_fee_cents"] == 19904
        assert order["mcf_fee_cents"] == 19000 + 1520 - 616
        assert order["fee_advantage_cents"] == 96
        assert order["recommended_channel"] == "MCF"
        assert order["order_status"] == "MCF_SHIPPED"

    def test_the_draw_empties_the_listing_and_suppresses_it_for_zero_fulfillable(self):
        """All 50 units leave through the MCF channel, so nothing fulfillable and nothing
        damaged remains and the fee lands on the seller's accrual.

        PRD 3.7: "A successful draw sets `order_status` to `MCF_SHIPPED`, increases the
        seller's `mcf_fee_accrued_cents` by the order's `mcf_fee_cents`, and recomputes
        listing health plus the seller's storage utilization."
        PRD 3.2: "When both hold, `listing_status` becomes `SUPPRESSED` and
        `suppression_reason` is pinned by priority, first match winning: `MISSING_INVENTORY`
        when the listing's `missing_units` is at least 1, otherwise `STRANDED_INVENTORY` when
        its `unfulfillable_units` is at least 1, otherwise `ZERO_FULFILLABLE`."

        Design: Corner/calculations/mcf_peak_month_surcharge_and_three_percent_tier_flip_channel_choice
        """
        ctx = self._fifty_units_in_stock_in_december()
        place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 50, 1.00, "ZONE_1", "MCF", 20000
        )

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["fulfillable_units"] == 0
        assert listing["inventory_health"] == "OUT_OF_STOCK"
        assert listing["listing_status"] == "SUPPRESSED"
        assert listing["suppression_reason"] == "ZERO_FULFILLABLE"
        assert read_seller(ctx["seller_id"])["mcf_fee_accrued_cents"] == 19904


class TestLiquidationRecoveryCeiling:
    """Same method, same units, two unit costs: the ceiling binds only on the dear one."""

    def _two_liquidations_of_sixty_units(self) -> dict:
        ctx = setup_baseline(listing={"sku": "SKU-CHEAP", "unit_cost_cents": 1250})
        rich = create_listing(ctx["seller_id"], sku="SKU-RICH", unit_cost_cents=3000)
        plan = create_plan(
            ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
        )
        cheap_line = add_line_item(plan["id"], ctx["seller_id"], ctx["listing_id"], 60)
        rich_line = add_line_item(plan["id"], ctx["seller_id"], rich["id"], 60)
        confirm_plan(plan["id"], ctx["seller_id"])
        ship_plan(plan["id"], ctx["seller_id"])
        receive_plan(
            plan["id"], ctx["fc_id"], [(cheap_line["id"], 60, 0), (rich_line["id"], 60, 0)]
        )
        cheap_lot = lots_for_listing(ctx["listing_id"], ctx["seller_id"])[0]
        rich_lot = lots_for_listing(rich["id"], ctx["seller_id"])[0]
        window = {
            "removal_method": "LIQUIDATION",
            "unit_pool": "FULFILLABLE",
            "removal_window_start": "2026-09-01T00:00:00Z",
            "removal_window_end": "2026-09-02T00:00:00Z",
        }
        ctx.update({
            "rich_listing_id": rich["id"],
            "cheap_lot_id": cheap_lot["id"],
            "rich_lot_id": rich_lot["id"],
            "cheap_order": request_removal(
                cheap_lot["id"], ctx["seller_id"], 60, **window
            ),
            "rich_order": request_removal(rich_lot["id"], ctx["seller_id"], 60, **window),
        })
        return ctx

    def test_a_requested_liquidation_reserves_the_units_and_prices_nothing_yet(self):
        """Both orders sit unpriced with their 60 units held in reservation rather than in
        the fulfillable pool.

        PRD 3.6: "A successful request opens at `status` of `REQUESTED` with
        `removal_fee_cents`, `liquidation_recovery_cents` and `net_settlement_cents` all at 0
        and `completed_at` null."
        PRD 3.6: "It reserves the units: `requested_units` is subtracted from whichever pool
        the `unit_pool` names and added to the lot's `units_reserved_for_removal`, leaving
        `units_received_total` unchanged."

        Design: Corner/calculations/liquidation_recovery_cap_binds_only_above_the_per_unit_ceiling
        """
        ctx = self._two_liquidations_of_sixty_units()
        for order in (ctx["cheap_order"], ctx["rich_order"]):
            assert order["status"] == "REQUESTED"
            assert order["removal_fee_cents"] == 0
            assert order["liquidation_recovery_cents"] == 0
            assert order["net_settlement_cents"] == 0

        cheap_lot = read_lot(ctx["cheap_lot_id"], ctx["seller_id"])
        assert cheap_lot["units_reserved_for_removal"] == 60
        assert cheap_lot["units_received_total"] == 60
        assert read_listing(ctx["listing_id"], ctx["seller_id"])["fulfillable_units"] == 0

    def test_completion_prices_five_percent_on_one_lot_and_the_ceiling_on_the_other(self):
        """The fee is 1500 on both, but the recovery is the 3750-cent five-percent term for
        the 1250-cent unit and the 7200-cent ceiling for the 3000-cent unit.

        PRD 3.6: "Under `LIQUIDATION`, there is no base and the fee is 25 cents per unit.
        `liquidation_recovery_cents` is 0 for every method other than `LIQUIDATION`; under
        `LIQUIDATION` it is the smaller of two figures — five percent of the requested units
        multiplied by the listing's `unit_cost_cents`, rounded half up to whole cents, and a
        hard ceiling of 120 cents per requested unit."
        PRD 3.6: "`net_settlement_cents` is `liquidation_recovery_cents` minus
        `removal_fee_cents`, and is therefore negative for disposal and return-to-seller."

        Design: Corner/calculations/liquidation_recovery_cap_binds_only_above_the_per_unit_ceiling
        """
        ctx = self._two_liquidations_of_sixty_units()
        set_clock("2026-09-01T00:00:00Z")
        complete_removal(ctx["cheap_order"]["id"], ctx["fc_id"])
        complete_removal(ctx["rich_order"]["id"], ctx["fc_id"])

        cheap = read_removal_order(ctx["cheap_order"]["id"], ctx["seller_id"])
        assert cheap["removal_fee_cents"] == 1500
        assert cheap["liquidation_recovery_cents"] == 3750
        assert cheap["net_settlement_cents"] == 2250

        rich = read_removal_order(ctx["rich_order"]["id"], ctx["seller_id"])
        assert rich["removal_fee_cents"] == 1500
        assert rich["liquidation_recovery_cents"] == 7200
        assert rich["net_settlement_cents"] == 5700

        assert read_lot(ctx["cheap_lot_id"], ctx["seller_id"])["units_removed"] == 60
        assert read_lot(ctx["rich_lot_id"], ctx["seller_id"])["units_removed"] == 60


class TestStorageBillingRunRecomputesUtilization:
    """The run is the only place a utilization downgrade can happen."""

    def _thirty_units_against_a_ten_cubic_foot_entitlement(self) -> dict:
        return setup_received_lot(
            units=30, seller={"storage_cubic_feet_entitlement": 10.0000}
        )

    def test_the_run_assesses_one_lot_and_restates_the_utilization_ratio(self):
        """30 cubic feet at 87 cents is a single 2610-cent assessment, and the same call is
        what lifts the seller's ratio to 3.0000.

        PRD 3.9: "`monthly_storage_fee_cents` is `billable_cubic_feet` multiplied by the
        holding centre's `monthly_storage_rate_cents_per_cubic_foot`, rounded half up to
        whole cents."
        PRD 3.9: "The seller's `storage_utilization_ratio` is that total divided by the
        seller's `storage_cubic_feet_entitlement`, rounded half up to four decimal places."

        Design: Corner/calculations/storage_billing_run_recomputes_utilization_and_downgrades_tier
        """
        ctx = self._thirty_units_against_a_ten_cubic_foot_entitlement()
        assert read_seller(ctx["seller_id"])["storage_utilization_ratio"] == pytest.approx(
            3.0
        )

        run = run_storage_billing()
        assert run["billing_run_sequence"] == 1
        assert run["assessment_count"] == 1
        assert run["total_assessed_cents"] == 2610

        seller = read_seller(ctx["seller_id"])
        assert seller["storage_utilization_ratio"] == pytest.approx(3.0)
        assert seller["storage_fee_accrued_cents"] == 2610

        lot = read_lot(ctx["lot_id"], ctx["seller_id"])
        assert lot["aged_bucket"] == "UNDER_181"
        assert lot["ltsf_exposed"] is False

    def test_the_same_run_steps_the_elevated_tier_down_without_moving_the_score(self):
        """The quota opened at 1000 points and a 3000-unit limit; the run adds one downgrade
        step, so the limit becomes 1500 while the score itself is unchanged.

        PRD 3.9: "When the recomputed `storage_utilization_ratio` is strictly greater than
        1.0000 and the seller has a quota period whose `status` is `ACTIVE`, that period's
        `capacity_tier_downgrade_steps` increases by exactly 1, and the inventory performance
        score is re-run for it so that `capacity_tier` and `restock_limit_units` reflect the
        new step count."
        PRD 3.1: "The effective `capacity_tier` is then that base tier shifted down by
        `capacity_tier_downgrade_steps`, one step per unit of that counter, where one step
        moves `TIER_ELEVATED` to `TIER_STANDARD` and `TIER_STANDARD` to `TIER_RESTRICTED`;
        `TIER_RESTRICTED` is the floor and further steps have no additional effect."

        Design: Corner/calculations/storage_billing_run_recomputes_utilization_and_downgrades_tier
        """
        ctx = self._thirty_units_against_a_ten_cubic_foot_entitlement()
        assert ctx["quota"]["iprs_score"] == 1000
        assert ctx["quota"]["capacity_tier"] == "TIER_ELEVATED"
        assert ctx["quota"]["restock_limit_units"] == 3000

        run = run_storage_billing()
        assert run["downgraded_quota_count"] == 1

        quota = read_quota(ctx["quota_id"], ctx["seller_id"])
        assert quota["capacity_tier_downgrade_steps"] == 1
        assert quota["capacity_tier"] == "TIER_STANDARD"
        assert quota["restock_limit_units"] == 1500
        assert quota["iprs_score"] == 1000
        assert quota["base_capacity_tier"] == "TIER_ELEVATED"


class TestReimbursementPerUnitCap:
    """The seller's cap, not the listing's cost, is the per-unit base when it is lower."""

    def test_the_lower_seller_cap_replaces_the_listing_unit_cost(self):
        """40 damaged units valued at the 1000-cent cap and scaled by the 0.90 warehouse
        factor pay 36000 cents, not the 45000 the listing's own cost would give.

        PRD 3.8: "The per-unit value is the smaller of the listing's `unit_cost_cents` and
        the seller's `unit_cost_cap_cents`."
        PRD 3.8: "A type factor scales the result: 1.00 for `LOST_INBOUND`, 0.90 for
        `DAMAGED_WAREHOUSE` and 0.80 for `LOST_REMOVAL`. `reimbursement_amount_cents` is the
        product of `eligible_units`, the per-unit value and the type factor, with round half
        up applied once to that whole product."

        Design: Corner/calculations/reimbursement_per_unit_value_clipped_by_seller_unit_cost_cap
        """
        ctx = setup_lot_with_split_pools(60, 40, seller={"unit_cost_cap_cents": 1000})
        assert ctx["listing"]["unit_cost_cents"] == 1250

        claim = file_claim(
            ctx["lot_id"], ctx["seller_id"], "DAMAGED_WAREHOUSE", 40, 3,
            evidence_reference="EV-DMG-40",
        )
        decided = decide_claim(
            claim["id"], "APPROVED", decision_note="warehouse damage confirmed"
        )
        assert decided["status"] == "APPROVED"
        assert decided["eligible_units"] == 40
        assert decided["approved_units"] == 40
        assert decided["reimbursement_amount_cents"] == 36000
        assert decided["reimbursement_amount_cents"] != 45000

        stored = read_claim(claim["id"])
        assert stored["decided_at"].startswith("2026-08-01T00:00:00")
        assert read_seller(ctx["seller_id"])["reimbursement_credit_cents"] == 36000
        assert read_lot(ctx["lot_id"], ctx["seller_id"])["unfulfillable_units"] == 0


class TestReplenishmentHeadroomClip:
    """A 2000-unit raw need is cut to the 500 units of quota the seller can still spend."""

    def test_the_recommendation_is_clipped_to_the_remaining_headroom(self):
        """The forecast wants 3000 units of coverage and sees 1000 already in flight, but the
        1500-unit limit is already 1000 consumed, so only 500 units are recommended.

        PRD 3.3: "`quota_headroom_units` is the larger of 0 and the seller's
        `restock_limit_units` minus its `utilized_units`, read from the quota period whose
        `status` is `ACTIVE`, and is 0 when the seller has no active period at all."
        PRD 3.3: "The raw need is the larger of 0 and `target_units` minus the listing's
        `fulfillable_units` minus `in_flight_units`, and `recommended_replenishment_units` is
        the smaller of that raw need and `quota_headroom_units` — so a recommendation is
        never larger than the capacity the seller could actually consume."

        Design: Corner/calculations/replenishment_recommendation_clipped_by_remaining_restock_headroom
        """
        ctx = setup_baseline(quota=STANDARD_TIER_METRICS)
        assert ctx["quota"]["iprs_score"] == 545
        assert ctx["quota"]["restock_limit_units"] == 1500

        create_in_transit_plan(
            ctx["seller_id"], ctx["fc_id"], ctx["listing_id"], 1000,
            "2026-08-10T00:00:00Z", "2026-08-11T00:00:00Z",
        )
        forecast = create_forecast(
            ctx["listing_id"], ctx["seller_id"], forecast_variant="TRAILING_30",
            trailing_30_units_sold=1500, prior_year_same_period_units_sold=0,
            seasonal_index=1.00, coverage_target_days=50, lead_time_days=10,
        )
        assert forecast["daily_velocity"] == pytest.approx(50.0)
        assert forecast["target_units"] == 3000
        assert forecast["in_flight_units"] == 1000
        assert forecast["quota_headroom_units"] == 500
        assert forecast["recommended_replenishment_units"] == 500
        assert forecast["stranded_risk_flag"] is False

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["recommended_replenishment_units"] == 500
        assert listing["fulfillable_units"] == 0
        assert read_seller(ctx["seller_id"])["restock_reserved_units"] == 1000


class TestZeroVelocityStrandedRisk:
    """Stock with no sales is flagged even when there is nothing to recommend."""

    def _sixty_fulfillable_and_forty_damaged(self) -> dict:
        return setup_lot_with_split_pools(60, 40, quota=STANDARD_TIER_METRICS)

    def test_no_sales_at_all_recommends_nothing_but_still_raises_the_flag(self):
        """A zero daily velocity gives a zero target and a zero recommendation, yet the 40
        damaged units alone are enough to raise the risk flag.

        PRD 3.3: "Under `TRAILING_30`, `daily_velocity` is `trailing_30_units_sold` divided
        by the 30-day trailing window, rounded half up to four decimal places; the prior-year
        figure and the `seasonal_index` are ignored even when supplied."
        PRD 3.3: "Finally, `stranded_risk_flag` is true when the listing's
        `unfulfillable_units` is greater than 0, or when `daily_velocity` is exactly 0.0000
        while the listing's `fulfillable_units` is greater than 0."

        Design: Corner/calculations/zero_velocity_with_stock_on_hand_raises_stranded_risk_flag
        """
        ctx = self._sixty_fulfillable_and_forty_damaged()
        assert ctx["quota"]["restock_limit_units"] == 1500

        forecast = create_forecast(
            ctx["listing_id"], ctx["seller_id"], forecast_variant="TRAILING_30",
            trailing_30_units_sold=0, prior_year_same_period_units_sold=0,
            seasonal_index=1.00, coverage_target_days=30, lead_time_days=0,
        )
        assert forecast["daily_velocity"] == pytest.approx(0.0)
        assert forecast["target_units"] == 0
        assert forecast["recommended_replenishment_units"] == 0
        assert forecast["stranded_risk_flag"] is True

    def test_the_second_forecast_covers_the_gap_above_the_units_on_hand(self):
        """1200 units sold gives a 40-unit daily velocity and a 1200-unit target, of which
        the 60 fulfillable units on hand are subtracted, and the flag stays up.

        PRD 3.3: "`target_units` is `daily_velocity` multiplied by the sum of
        `coverage_target_days` and `lead_time_days`, rounded **up** to the next whole unit."
        PRD 3.3: "Each forecast is written as a new immutable row, and its
        `recommended_replenishment_units` is copied onto the listing; the listing therefore
        always reflects the most recent forecast, meaning the forecast row with the latest
        `created_at`."

        Design: Corner/calculations/zero_velocity_with_stock_on_hand_raises_stranded_risk_flag
        """
        ctx = self._sixty_fulfillable_and_forty_damaged()
        create_forecast(
            ctx["listing_id"], ctx["seller_id"], forecast_variant="TRAILING_30",
            trailing_30_units_sold=0, prior_year_same_period_units_sold=0,
            seasonal_index=1.00, coverage_target_days=30, lead_time_days=0,
        )
        second = create_forecast(
            ctx["listing_id"], ctx["seller_id"], forecast_variant="TRAILING_30",
            trailing_30_units_sold=1200, prior_year_same_period_units_sold=0,
            seasonal_index=1.00, coverage_target_days=30, lead_time_days=0,
        )
        assert second["daily_velocity"] == pytest.approx(40.0)
        assert second["target_units"] == 1200
        assert second["recommended_replenishment_units"] == 1140
        assert second["stranded_risk_flag"] is True

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["fulfillable_units"] == 60
        assert listing["unfulfillable_units"] == 40
        assert listing["recommended_replenishment_units"] == 1140
        assert newest_quota(ctx["seller_id"])["utilized_units"] == 100


class TestMcfDrawIsFifoAcrossTwoLots:
    """Two lots of one SKU at two centres; the draw follows first_received_at, not id."""

    def _an_older_and_a_newer_lot(self) -> dict:
        ctx = setup_baseline(quota={"base_capacity_units": 3000})
        first = create_in_transit_plan(
            ctx["seller_id"], ctx["fc_id"], ctx["listing_id"], 50,
            "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z",
        )
        receive_plan(first["plan"]["id"], ctx["fc_id"], [(first["line_item"]["id"], 50, 0)])

        second_centre = register_fulfillment_center(fc_code="FC-B2")
        later = create_in_transit_plan(
            ctx["seller_id"], second_centre["id"], ctx["listing_id"], 100,
            "2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z",
        )
        set_clock("2026-08-20T00:00:00Z")
        receive_plan(
            later["plan"]["id"], second_centre["id"], [(later["line_item"]["id"], 100, 0)]
        )

        lots = lots_for_listing(ctx["listing_id"], ctx["seller_id"])
        assert len(lots) == 2
        ctx.update({
            "second_fc_id": second_centre["id"],
            "older_lot_id": lots[0]["id"],
            "newer_lot_id": lots[1]["id"],
        })
        return ctx

    def test_the_draw_drains_the_older_lot_before_touching_the_newer_one(self):
        """70 units take all 50 of the August 1st lot and only 20 of the August 20th lot,
        which depletes the first and leaves 80 units behind in the second.

        PRD 3.7: "Candidate lots are those whose listing matches the order's
        `sku_listing_id`, whose `lot_status` is `ACTIVE` or `PARTIALLY_REMOVED`, whose
        `fulfillable_units` is at least 1, and whose holding centre's `receiving_status` is
        not `SUSPENDED`; they are walked in ascending `first_received_at` order with
        ascending `created_at` as tie-break."
        PRD 3.7: "The walk stops as soon as the remaining need reaches zero."

        Design: Corner/calculations/mcf_draw_consumes_oldest_lot_first_across_two_lots
        """
        ctx = self._an_older_and_a_newer_lot()
        order = place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 70, 1.00, "ZONE_2", "MCF", 90000
        )
        assert order["units"] == 70
        assert order["consumed_lot_allocations"] == [
            {"inventory_lot_id": ctx["older_lot_id"], "units": 50},
            {"inventory_lot_id": ctx["newer_lot_id"], "units": 20},
        ]

        older = read_lot(ctx["older_lot_id"], ctx["seller_id"])
        assert older["fulfillable_units"] == 0
        assert older["units_shipped_mcf"] == 50
        assert older["lot_status"] == "DEPLETED"

        newer = read_lot(ctx["newer_lot_id"], ctx["seller_id"])
        assert newer["fulfillable_units"] == 80
        assert newer["units_shipped_mcf"] == 20
        assert newer["lot_status"] == "ACTIVE"

        listing = read_listing(ctx["listing_id"], ctx["seller_id"])
        assert listing["fulfillable_units"] == 80
        assert listing["inventory_health"] == "HEALTHY"

    def test_the_august_quote_takes_the_three_percent_tier_with_no_peak_surcharge(self):
        """Zone 2 at 458 cents for 70 units is 32060 pre-discount in a non-peak month, so the
        3% tier applies and MCF beats the seller's own 90000-cent quote by 58902.

        PRD 3.7: "The zone base fee is 380 cents for `ZONE_1`, 458 cents for `ZONE_2` and 540
        cents for `ZONE_3`."
        PRD 3.7: "`fee_advantage_cents` is `self_fulfilled_cost_cents` minus
        `mcf_fee_cents`, and `recommended_channel` is `MCF` when that advantage is at least 0
        and `SELF_FULFILLED` when it is negative — an exact tie of zero resolves to `MCF`."

        Design: Corner/calculations/mcf_draw_consumes_oldest_lot_first_across_two_lots
        """
        ctx = self._an_older_and_a_newer_lot()
        order = place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 70, 1.00, "ZONE_2", "MCF", 90000
        )
        assert order["is_peak_period"] is False
        assert order["mcf_fee_cents"] == 31098
        assert order["fee_advantage_cents"] == 58902
        assert order["recommended_channel"] == "MCF"
        assert order["order_status"] == "MCF_SHIPPED"
