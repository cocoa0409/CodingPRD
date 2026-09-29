"""Arithmetic that must be reproduced exactly: tiers, waterfalls and rounding.

Every figure asserted here is derived by hand from the stated formula, so a plausible
but different order of operations — a pooled round instead of a per-item one, a
category-ordered allocation instead of a chronological one, a blended sell-through
rate instead of six constants — produces a visibly different number.
"""
import pytest

from test_helpers import (
    add_inventory_lot,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    approve_expense_item,
    assert_engagement_expense_identity,
    assert_expense_shares_conserved,
    assert_inventory_lot,
    assert_lease_disposition,
    assert_recovery_summary,
    assert_settlement,
    assert_settlement_closing_identity,
    assert_surrender_waterfall_invariants,
    close_store,
    create_engagement,
    create_jurisdiction,
    decide_license,
    dispute_settlement,
    make_compliance_headers,
    make_consultant_headers,
    open_lease_disposition,
    open_settlement,
    pin_clock,
    post_sales_day,
    propose_settlement,
    read_engagement,
    read_store,
    record_landlord_response,
    reject_sales_day,
    send_lease_offer,
    submit_engagement,
    submit_expense_item,
    surrender_lease,
    validate_paginated,
    validate_success,
)

NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "augmentation_prohibited": False, "prohibited_claim_codes": [],
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}
APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
ELECTRONICS_LOT = {
    "category": "ELECTRONICS", "source": "ORIGINAL", "units_initial": 200,
    "unit_cost_cents": 15000, "unit_retail_cents": 30000,
}
LICENSE_PERIOD = {
    "period_start_date": "2026-09-15", "period_end_date": "2026-10-14",
    "advertising_claim_codes": ["EVERYTHING_MUST_GO"],
}


def _license_the_store(store_id, license_number):
    license_row = apply_for_license(
        store_id, license_number=license_number, **LICENSE_PERIOD
    )
    return decide_license(license_row["id"])


def _lots_of(store_id):
    rows, _meta = validate_paginated(
        api_client.list_inventory_lots(store_id, make_consultant_headers())
    )
    return {row["id"]: row for row in rows}


def _store_one_cent_below_the_middle_fee_band():
    """A 5,000,000-cent base with 2,999,500 of posted original sales.

    2,999,500 / 5,000,000 is exactly 0.5999, one ten-thousandth below the boundary,
    and a further 500 cents of sales lands the ratio on exactly 0.6000.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-3001", address_line="S-3001 Liquidation Row",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    _license_the_store(store["id"], "NY-GOB-3001")
    post_sales_day(
        store["id"], business_date="2026-09-15",
        original_net_sales_cents=2999500, augmentation_net_sales_cents=0,
        original_units_sold=600, augmentation_units_sold=0,
    )
    worksheet = open_settlement(engagement["id"], "PROVISIONAL")
    return {"engagement": engagement, "store": store, "worksheet": worksheet}


def _re_propose_after_one_more_cent_of_sales(scenario):
    """Dispute the first proposal, post 500 cents more, and propose again."""
    dispute_settlement(scenario["worksheet"]["id"])
    pin_clock("2026-09-16T00:00:00Z")
    post_sales_day(
        scenario["store"]["id"], business_date="2026-09-16",
        original_net_sales_cents=500, augmentation_net_sales_cents=0,
        original_units_sold=1, augmentation_units_sold=0,
    )
    return propose_settlement(scenario["worksheet"]["id"])


class TestFeeTierBoundaryIsInclusiveAtTheBottomOfEachBand:
    def test_a_ratio_of_zero_point_five_nine_nine_nine_stays_in_the_low_band(self):
        """One ten-thousandth below 0.60 still draws the 2 percent rate.

        The PRD says: "The `fee_rate` is then selected from the ratio by a three-band
        tier table: a ratio below 0.60 draws 0.0200, a ratio from 0.60 up to but
        excluding 0.80 draws 0.0350, and a ratio of 0.80 or more draws 0.0500."

        Design: Corner/calculations/fee_tier_flips_at_recovery_ratio_exactly_zero_point_six_zero_zero_zero
        """
        scenario = _store_one_cent_below_the_middle_fee_band()
        proposed = propose_settlement(scenario["worksheet"]["id"])
        assert_settlement(proposed)
        assert proposed["recovery_ratio"] == pytest.approx(0.5999, abs=0.00001)
        assert proposed["fee_rate"] == pytest.approx(0.0200, abs=0.00001)
        assert proposed["gross_recovery_cents"] == 2999500
        assert proposed["liquidator_fee_cents"] == 59990
        assert proposed["retailer_proceeds_cents"] == 2939510
        assert proposed["liquidator_proceeds_cents"] == 59990
        assert_settlement_closing_identity(proposed)

    def test_the_dispute_records_a_round_without_touching_the_money(self):
        """DISPUTED at round one, ready for the re-computation.

        The PRD says: "A dispute takes the worksheet `PROPOSED → DISPUTED`, records the
        `dispute_reason`, and increments `dispute_round` by 1; the consultant may then
        re-propose, closing the loop, and the cycle may repeat without bound —
        `dispute_round` counts the trips but never caps them."

        Design: Corner/calculations/fee_tier_flips_at_recovery_ratio_exactly_zero_point_six_zero_zero_zero
        """
        scenario = _store_one_cent_below_the_middle_fee_band()
        propose_settlement(scenario["worksheet"]["id"])
        disputed = dispute_settlement(scenario["worksheet"]["id"])
        assert disputed["settlement_status"] == "DISPUTED"
        assert disputed["dispute_round"] == 1
        assert disputed["liquidator_fee_cents"] == 59990

    def test_a_ratio_of_exactly_zero_point_six_belongs_to_the_higher_band(self):
        """500 more cents of sales costs the retailer 45,010 cents of fee.

        The PRD says: "Both boundaries belong to the higher band, so a ratio of exactly
        0.6000 is charged at 0.0350 and a ratio of exactly 0.8000 is charged at 0.0500."

        Design: Corner/calculations/fee_tier_flips_at_recovery_ratio_exactly_zero_point_six_zero_zero_zero
        """
        scenario = _store_one_cent_below_the_middle_fee_band()
        propose_settlement(scenario["worksheet"]["id"])
        reproposed = _re_propose_after_one_more_cent_of_sales(scenario)
        assert reproposed["original_net_sales_cents"] == 3000000
        assert reproposed["recovery_ratio"] == pytest.approx(0.6000, abs=0.00001)
        assert reproposed["fee_rate"] == pytest.approx(0.0350, abs=0.00001)
        assert reproposed["liquidator_fee_cents"] == 105000
        assert reproposed["retailer_proceeds_cents"] == 2895000
        assert reproposed["liquidator_proceeds_cents"] == 105000
        assert reproposed["liquidator_fee_cents"] - 59990 == 45010
        assert_settlement_closing_identity(reproposed)


LEASE_CLAIMS = {
    "landlord_name": "Kestrel Realty", "daily_holdover_rate_cents": 25000,
    "rent_arrears_cents": 400000, "cam_arrears_cents": 150000,
    "restoration_cost_cents": 600000, "fixture_reserve_price_cents": 500000,
    "surrender_credit_cents": 0,
}


def _two_closed_stores_with_identical_lease_claims():
    """The same 1,150,000 of claims on both leases, one of them past its deadline.

    Store A's deadline is 2026-12-01 so it never goes into holdover; store B's is
    2026-10-11, five days before the 2026-10-16 surrender.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    stores = {}
    for suffix in ("A", "B"):
        store = add_store(
            engagement["id"], jurisdiction["id"],
            store_code=f"S-3002{suffix}",
            address_line=f"S-3002{suffix} Liquidation Row",
        )
        add_inventory_lot(store["id"], **APPAREL_LOT)
        stores[suffix] = store
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    leases = {}
    for suffix, deadline in (("A", "2026-12-01"), ("B", "2026-10-11")):
        _license_the_store(stores[suffix]["id"], f"NY-GOB-3002{suffix}")
        lease = open_lease_disposition(
            stores[suffix]["id"], surrender_deadline_date=deadline, **LEASE_CLAIMS
        )
        send_lease_offer(lease["id"], 300000)
        leases[suffix] = record_landlord_response(lease["id"], "ACCEPT")
    for suffix in ("A", "B"):
        close_store(stores[suffix]["id"])
    pin_clock("2026-10-16T00:00:00Z")
    return {"engagement": engagement, "stores": stores, "leases": leases}


class TestSurrenderWaterfallOrdering:
    def test_short_funds_stop_part_way_through_the_third_bucket(self):
        """1,000,000 pays rent and CAM in full and only 450,000 of restoration.

        The PRD says: "Each bucket in turn takes the smaller of the funds still
        remaining and its own claim amount, that amount is written to the matching
        `allocated_rent_cents`, `allocated_cam_cents`, `allocated_restoration_cents`, or
        `allocated_holdover_cents` field, and the remaining funds are reduced by what
        was taken."

        Design: Corner/calculations/surrender_waterfall_fills_four_buckets_in_order_leaving_unpaid_balance_or_residual
        """
        scenario = _two_closed_stores_with_identical_lease_claims()
        surrendered = surrender_lease(scenario["leases"]["A"]["id"], 1000000)
        assert_lease_disposition(surrendered)
        assert surrendered["holdover_days"] == 0
        assert surrendered["holdover_penalty_cents"] == 0
        assert surrendered["allocated_rent_cents"] == 400000
        assert surrendered["allocated_cam_cents"] == 150000
        assert surrendered["allocated_restoration_cents"] == 450000
        assert surrendered["allocated_holdover_cents"] == 0
        assert surrendered["unpaid_landlord_balance_cents"] == 150000
        assert surrendered["residual_to_retailer_cents"] == 0
        assert_surrender_waterfall_invariants(surrendered)

    def test_ample_funds_fill_all_four_buckets_and_return_the_residual(self):
        """2,000,000 against 1,337,500 of claims leaves 662,500 for the retailer.

        The PRD says: "The `residual_to_retailer_cents` is the available funds less the
        total of the four claim amounts, floored at 0, which is what comes back to the
        retailer when the fixtures sold for more than the landlord could claim."

        Design: Corner/calculations/surrender_waterfall_fills_four_buckets_in_order_leaving_unpaid_balance_or_residual
        """
        scenario = _two_closed_stores_with_identical_lease_claims()
        surrendered = surrender_lease(scenario["leases"]["B"]["id"], 2000000)
        assert surrendered["allocated_rent_cents"] == 400000
        assert surrendered["allocated_cam_cents"] == 150000
        assert surrendered["allocated_restoration_cents"] == 600000
        assert surrendered["allocated_holdover_cents"] == 187500
        assert surrendered["unpaid_landlord_balance_cents"] == 0
        assert surrendered["residual_to_retailer_cents"] == 662500
        assert_surrender_waterfall_invariants(surrendered)

    def test_the_holdover_penalty_carries_the_one_point_five_multiplier(self):
        """Five days past the deadline at 25,000 a day gives 187,500, not 125,000.

        The PRD says: "The `holdover_penalty_cents` figure is the
        `daily_holdover_rate_cents` multiplied by `holdover_days` multiplied by a
        holdover multiplier of 1.5, rounded half up to whole cents; the penalty rate is
        deliberately punitive, and the multiplier applies to the whole penalty, not to
        each day separately, so the rounding happens exactly once here and never again
        inside the allocation."

        Design: Corner/calculations/surrender_waterfall_fills_four_buckets_in_order_leaving_unpaid_balance_or_residual
        """
        scenario = _two_closed_stores_with_identical_lease_claims()
        surrendered = surrender_lease(scenario["leases"]["B"]["id"], 2000000)
        assert surrendered["holdover_days"] == 5
        assert surrendered["holdover_penalty_cents"] == 187500

    def test_both_surrenders_carry_their_own_store_out_of_closed(self):
        """The two dispositions are terminal and the two stores follow them.

        The PRD says: "Surrender stamps `surrendered_at` with the current logical-clock
        instant, takes the owning store `CLOSED → SURRENDERED`, and increments both the
        disposition's and the store's `version` by 1."

        Design: Corner/calculations/surrender_waterfall_fills_four_buckets_in_order_leaving_unpaid_balance_or_residual
        """
        scenario = _two_closed_stores_with_identical_lease_claims()
        first = surrender_lease(scenario["leases"]["A"]["id"], 1000000)
        second = surrender_lease(scenario["leases"]["B"]["id"], 2000000)
        assert first["disposition_status"] == "SURRENDERED"
        assert second["disposition_status"] == "SURRENDERED"
        for suffix in ("A", "B"):
            assert read_store(scenario["stores"][suffix]["id"])[
                "store_status"
            ] == "SURRENDERED"


def _store_with_one_posted_and_one_rejected_day():
    """120,000 cents posted on 40 units, then 999,999 on 300 units rejected.

    Only the posted day may reach the realized figures, and only the posted day's
    units may leave the lot.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-3003", address_line="S-3003 Liquidation Row",
    )
    lot = add_inventory_lot(store["id"], **APPAREL_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    _license_the_store(store["id"], "NY-GOB-3003")
    post_sales_day(
        store["id"], business_date="2026-09-15",
        original_net_sales_cents=120000, augmentation_net_sales_cents=0,
        original_units_sold=40, augmentation_units_sold=0,
    )
    pin_clock("2026-09-16T00:00:00Z")
    rejected = reject_sales_day(
        store["id"], reject_reason="register mis-key", business_date="2026-09-16",
        original_net_sales_cents=999999, augmentation_net_sales_cents=0,
        original_units_sold=300, augmentation_units_sold=0,
    )
    return {
        "engagement": engagement, "store": store, "lot": lot, "rejected": rejected,
    }


class TestRejectedDaysAreExcludedEverywhere:
    def test_the_rejected_money_never_reaches_the_realized_figures(self):
        """Realized recovery is the posted 120,000 alone, at ratio 0.0600.

        The PRD says: "The store's `realized_gross_recovery_cents` is the sum of
        `net_sales_cents` over its selling days whose status is `POSTED`; days still in
        review and rejected days contribute nothing."

        Design: Corner/calculations/rejected_sales_day_stays_out_of_the_realized_variant_and_out_of_inventory
        """
        scenario = _store_with_one_posted_and_one_rejected_day()
        assert scenario["rejected"]["day_status"] == "REJECTED"
        store = read_store(scenario["store"]["id"])
        assert store["realized_gross_recovery_cents"] == 120000
        assert store["realized_recovery_ratio"] == pytest.approx(0.0600, abs=0.00001)
        assert store["units_sold_total"] == 40
        assert store["realized_sell_through_pct"] == pytest.approx(
            0.0400, abs=0.00001
        )

    def test_the_rejected_units_were_never_allocated_to_the_lot(self):
        """Nine hundred and sixty units are still on the floor.

        The PRD says: "A posting takes the day `PENDING_REVIEW → POSTED`, stamps
        `posted_at` with the current logical-clock instant, records
        `reviewed_by_user_id`, and consumes inventory."

        Design: Corner/calculations/rejected_sales_day_stays_out_of_the_realized_variant_and_out_of_inventory
        """
        scenario = _store_with_one_posted_and_one_rejected_day()
        lot = _lots_of(scenario["store"]["id"])[scenario["lot"]["id"]]
        assert_inventory_lot(lot)
        assert lot["units_on_hand"] == 960
        assert lot["units_sold"] == 40
        assert lot["units_returned"] == 0
        assert lot["lot_status"] == "ON_FLOOR"

    def test_the_recovery_summary_reports_the_same_filtered_figures(self):
        """The computed read agrees with the store rather than double-counting.

        The PRD says: "Augmentation revenue therefore lifts realized gross recovery but
        not the realized recovery ratio."

        Design: Corner/calculations/rejected_sales_day_stays_out_of_the_realized_variant_and_out_of_inventory
        """
        scenario = _store_with_one_posted_and_one_rejected_day()
        summary = validate_success(
            api_client.get_recovery_summary(
                scenario["engagement"]["id"], make_consultant_headers()
            )
        )
        assert_recovery_summary(summary)
        assert summary["realized_gross_recovery_cents"] == 120000
        assert summary["realized_recovery_ratio"] == pytest.approx(
            0.0600, abs=0.00001
        )
        assert summary["store_count"] == 1


JEWELRY_LOT = {
    "category": "JEWELRY", "source": "ORIGINAL", "units_initial": 100,
    "unit_cost_cents": 10000, "unit_retail_cents": 40000,
}


def _draft_store_with_an_apparel_and_a_jewelry_lot():
    """One store, two categories, two different sell-through constants.

    APPAREL at 0.85 over 1,000 units and JEWELRY at 0.60 over 100 units, with no
    markdown stage anywhere so the planned discount stays 0.0000.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-3004", address_line="S-3004 Liquidation Row",
    )
    return {
        "engagement": engagement,
        "store": store,
        "apparel": add_inventory_lot(store["id"], **APPAREL_LOT),
        "jewelry": add_inventory_lot(store["id"], **JEWELRY_LOT),
    }


class TestCategorySellThroughConstantsAreAppliedPerLot:
    def test_each_lot_uses_the_constant_of_its_own_category(self):
        """850 apparel units at 5,000 and 60 jewellery units at 40,000.

        The PRD says: "Then, for every lot of the store whose status is `ON_FLOOR` or
        `SOLD_OUT` — of either source, and excluding lots already returned to their
        supplier — the projected unit count is the lot's initial units less its returned
        units, multiplied by that lot's category sell-through rate and floored to a whole
        unit."

        Design: Corner/calculations/category_sell_through_constants_are_applied_per_lot_category
        """
        scenario = _draft_store_with_an_apparel_and_a_jewelry_lot()
        lots = _lots_of(scenario["store"]["id"])
        assert lots[scenario["apparel"]["id"]]["projected_recovery_cents"] == 4250000
        assert lots[scenario["jewelry"]["id"]]["projected_recovery_cents"] == 2400000

    def test_no_blended_rate_can_reproduce_the_store_total(self):
        """6,650,000 over a 3,000,000 base is a ratio of 2.2167.

        The PRD says: "The store's `projected_gross_recovery_cents` is the exact integer
        sum of those per-lot rounded amounts — rounded per lot first, summed second."

        Design: Corner/calculations/category_sell_through_constants_are_applied_per_lot_category
        """
        scenario = _draft_store_with_an_apparel_and_a_jewelry_lot()
        store = read_store(scenario["store"]["id"])
        assert store["projected_gross_recovery_cents"] == 6650000
        assert store["original_cost_value_cents"] == 3000000
        assert store["projected_recovery_ratio"] == pytest.approx(
            2.2167, abs=0.00001
        )

    def test_the_submit_recomputation_carries_the_same_total_upward(self):
        """The engagement adopts the store's figures and derives no guaranty.

        The PRD says: "`original_cost_value_cents` is re-summed from the cost value of
        every original-merchandise lot across every store of the engagement,
        `guaranty_amount_cents` is re-derived as that original cost value multiplied by
        `guaranty_pct` and rounded half up to whole cents for a `GUARANTEED` or `HYBRID`
        agreement and set to exactly 0 for a `FEE_BASED` one, and
        `projected_gross_recovery_cents` and `projected_shortfall_cents` are recomputed
        as described in §3.2."

        Design: Corner/calculations/category_sell_through_constants_are_applied_per_lot_category
        """
        scenario = _draft_store_with_an_apparel_and_a_jewelry_lot()
        submitted = submit_engagement(scenario["engagement"]["id"])
        assert submitted["projected_gross_recovery_cents"] == 6650000
        assert submitted["original_cost_value_cents"] == 3000000
        assert submitted["guaranty_amount_cents"] == 0
        assert submitted["projected_shortfall_cents"] == 0


HOME_LOT = {
    "category": "HOME", "source": "ORIGINAL", "units_initial": 100,
    "unit_cost_cents": 1000, "unit_retail_cents": 3000,
}
LATER_APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 300,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}


def _store_whose_older_lot_is_the_home_one():
    """The HOME lot is created first and the larger APPAREL lot second.

    Category order would take APPAREL first and largest-first would too, so the
    150-unit day separates chronological order from both alternatives.  The clock
    is advanced between the two creates — still inside 2026-09-15 so every date
    computation is unchanged — so the two lots carry genuinely different
    `created_at` instants and the tie-break on `category` never engages.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-3005", address_line="S-3005 Liquidation Row",
    )
    home = add_inventory_lot(store["id"], **HOME_LOT)
    pin_clock("2026-09-15T01:00:00Z")
    apparel = add_inventory_lot(store["id"], **LATER_APPAREL_LOT)
    pin_clock("2026-09-15T02:00:00Z")
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    _license_the_store(store["id"], "NY-GOB-3005")
    day = post_sales_day(
        store["id"], business_date="2026-09-15",
        original_net_sales_cents=300000, augmentation_net_sales_cents=0,
        original_units_sold=150, augmentation_units_sold=0,
    )
    return {
        "engagement": engagement, "store": store,
        "home": home, "apparel": apparel, "day": day,
    }


class TestAllocationRunsOldestLotFirst:
    def test_the_older_home_lot_is_drained_before_the_newer_one_is_touched(self):
        """All 100 HOME units go, leaving the lot sold out.

        The PRD says: "Candidates are ordered by `created_at` ascending — never by lot
        id and never by category ordering — and where two lots of the same source share
        a `created_at` down to the millisecond, the tie is broken by taking the lot whose
        `category` enum name sorts lexicographically earlier first."

        Design: Corner/calculations/unit_allocation_drains_the_oldest_lot_before_the_newer_one
        """
        scenario = _store_whose_older_lot_is_the_home_one()
        lots = _lots_of(scenario["store"]["id"])
        home = lots[scenario["home"]["id"]]
        assert home["units_sold"] == 100
        assert home["units_on_hand"] == 0
        assert home["lot_status"] == "SOLD_OUT"

    def test_the_newer_apparel_lot_absorbs_only_the_remaining_fifty(self):
        """250 of the 300 apparel units are still on the floor.

        The PRD says: "Walking that order, each lot absorbs the smaller of the units
        still to be allocated and its own `units_on_hand`: the taken quantity is added to
        the lot's `units_sold`, its `units_on_hand` is recomputed as `units_initial` less
        `units_sold` less `units_returned`, and the allocation moves to the next lot
        until the day's units for that source are exhausted."

        Design: Corner/calculations/unit_allocation_drains_the_oldest_lot_before_the_newer_one
        """
        scenario = _store_whose_older_lot_is_the_home_one()
        lots = _lots_of(scenario["store"]["id"])
        apparel = lots[scenario["apparel"]["id"]]
        assert apparel["units_sold"] == 50
        assert apparel["units_on_hand"] == 250
        assert apparel["lot_status"] == "ON_FLOOR"

    def test_the_allocation_note_traces_the_two_takes_in_the_order_made(self):
        """The HOME lot's take is recorded before the APPAREL lot's.

        The PRD says: "The takes are written, in the order they were made, into the day's
        `allocation_note` as a trace naming each source, the units taken, and the lot
        that supplied them — for instance four hundred original units drawn from one lot
        followed by one hundred and fifty augmentation units drawn from another."

        Design: Corner/calculations/unit_allocation_drains_the_oldest_lot_before_the_newer_one
        """
        scenario = _store_whose_older_lot_is_the_home_one()
        note = scenario["day"]["allocation_note"]
        assert isinstance(note, str) and note.strip()
        home_at = note.find(scenario["home"]["id"])
        apparel_at = note.find(scenario["apparel"]["id"])
        assert home_at >= 0, "the trace must name the lot that supplied the units"
        assert apparel_at >= 0, "the trace must name the lot that supplied the units"
        assert home_at < apparel_at

    def test_the_store_totals_add_up_across_both_lots(self):
        """150 of 400 units sold is a sell-through of 0.3750.

        The PRD says: "Its `units_sold_total` is the sum of `units_sold` across all its
        lots, and `realized_sell_through_pct` is that total divided by
        `units_initial_total`, rounded half up to four decimal places and exactly 0.0000
        when `units_initial_total` is 0."

        Design: Corner/calculations/unit_allocation_drains_the_oldest_lot_before_the_newer_one
        """
        scenario = _store_whose_older_lot_is_the_home_one()
        store = read_store(scenario["store"]["id"])
        assert store["units_sold_total"] == 150
        assert store["units_initial_total"] == 400
        assert store["realized_sell_through_pct"] == pytest.approx(
            0.3750, abs=0.00001
        )


class TestLicenceDenialIsOutsideTheStrikeInputSet:
    def test_a_denied_application_costs_the_engagement_nothing(self):
        """DENIED, no strike, an OPEN posture and a store still waiting.

        The PRD says: "A denial moves the licence `APPLIED → DENIED`, leaves the store
        exactly where it was in `LICENSE_PENDING`, and — this is the distinction that
        matters most for §2.8 — records no compliance strike at all."

        Design: Corner/calculations/license_denial_produces_no_compliance_strike
        """
        pin_clock("2026-09-15T00:00:00Z")
        jurisdiction = create_jurisdiction(**NY_RULES)
        engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
        store = add_store(
            engagement["id"], jurisdiction["id"],
            store_code="S-3006", address_line="S-3006 Liquidation Row",
        )
        add_inventory_lot(store["id"], **APPAREL_LOT)
        submit_engagement(engagement["id"])
        approve_engagement(engagement["id"])
        license_row = apply_for_license(
            store["id"], license_number="NY-GOB-3006", **LICENSE_PERIOD
        )
        denied = decide_license(
            license_row["id"], decision="DENY", decision_reason="incomplete filing"
        )
        assert denied["license_status"] == "DENIED"
        assert denied["decided_by_user_id"] == "co-2"
        read_back = read_engagement(engagement["id"], make_compliance_headers())
        assert read_back["compliance_strike_count"] == 0
        assert read_back["compliance_posture"] == "OPEN"
        store_read = read_store(store["id"], make_compliance_headers())
        assert store_read["store_status"] == "LICENSE_PENDING"
        assert store_read["selling_start_date"] is None
        assert store_read["version"] == 2


SHARED_AT_THIRTY_FIVE = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "SHARED",
    "shared_expense_liquidator_pct": 0.35, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}


def _engagement_with_two_identical_odd_expenses():
    """Two ADVERTISING items of 333,333 cents against a SHARED 35 percent split.

    333,333 x 0.35 is 116,666.55, which rounds half up to 116,667 per item; the
    pooled alternative, 666,666 x 0.35 == 233,333.1, rounds to 233,333.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**SHARED_AT_THIRTY_FIVE)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-3007", address_line="S-3007 Liquidation Row",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    _license_the_store(store["id"], "NY-GOB-3007")
    items = [
        submit_expense_item(
            engagement["id"], store_id=store["id"],
            expense_category="ADVERTISING", amount_cents=333333,
            incurred_date="2026-09-15",
        )
        for _ in range(2)
    ]
    return {"engagement": engagement, "store": store, "items": items}


class TestSharedExpenseRoundsOncePerItem:
    def test_each_item_rounds_its_own_share_half_up(self):
        """116,667 to the liquidator and the 216,666 remainder to the retailer.

        The PRD says: "Under `LIQUIDATOR` responsibility the liquidator's share is the
        item's whole `amount_cents`; under `RETAILER` responsibility it is 0; under
        `SHARED` responsibility it is `amount_cents` multiplied by the engagement's
        `shared_expense_liquidator_pct`, rounded half up to whole cents once per item."

        Design: Corner/calculations/shared_expense_rounds_per_item_so_two_odd_items_total_one_cent_above_a_pooled_round
        """
        scenario = _engagement_with_two_identical_odd_expenses()
        for item in scenario["items"]:
            approved = approve_expense_item(item["id"])
            assert approved["liquidator_share_cents"] == 116667
            assert approved["retailer_share_cents"] == 216666
            assert_expense_shares_conserved(approved)

    def test_the_liquidator_aggregate_lands_one_cent_above_a_pooled_round(self):
        """233,334 is the sum of two per-item rounds; a pooled round gives 233,333.

        The PRD says: "The engagement's three aggregates are then re-summed over its
        items whose `expense_status` is `APPROVED` or `SETTLED`, excluding those still
        `SUBMITTED` and those `VOIDED`: `expense_total_cents` over `amount_cents`,
        `expense_liquidator_share_cents` over `liquidator_share_cents`, and
        `expense_retailer_share_cents` over `retailer_share_cents`."

        Design: Corner/calculations/shared_expense_rounds_per_item_so_two_odd_items_total_one_cent_above_a_pooled_round
        """
        scenario = _engagement_with_two_identical_odd_expenses()
        for item in scenario["items"]:
            approve_expense_item(item["id"])
        engagement = read_engagement(scenario["engagement"]["id"])
        assert engagement["expense_total_cents"] == 666666
        assert engagement["expense_liquidator_share_cents"] == 233334
        assert engagement["expense_retailer_share_cents"] == 433332
        assert engagement["expense_liquidator_share_cents"] != 233333
        assert_engagement_expense_identity(engagement)
