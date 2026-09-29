"""The two halves of the recovery duality, computed from one set of stored facts.

Projected recovery is the forward-looking category-sell-through estimate
discounted by the planned cadence; realized recovery counts only posted selling
days.  Both are read from the same store in the same response.
"""
import pytest

from test_helpers import (
    activate_markdown_stage,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_recovery_summary,
    create_engagement,
    create_jurisdiction,
    decide_license,
    get_success_data,
    make_controller_headers,
    pin_clock,
    read_store,
    store_manager_headers,
    submit_engagement,
    validate_success,
)

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
ELECTRONICS_LOT = {
    "category": "ELECTRONICS", "source": "ORIGINAL", "units_initial": 200,
    "unit_cost_cents": 15000, "unit_retail_cents": 30000,
}


def _post_day(store, **fields):
    """File a selling day as the store's own manager and have the retailer post it."""
    payload = {
        "business_date": "2026-09-16", "original_net_sales_cents": 1200000,
        "augmentation_net_sales_cents": 0, "original_units_sold": 300,
        "augmentation_units_sold": 0,
    }
    payload.update(fields)
    day = get_success_data(
        api_client.create_sales_day(store["id"], payload, store_manager_headers(store))
    )
    return get_success_data(
        api_client.review_sales_day(
            day["id"], {"decision": "POST"}, make_controller_headers()
        )
    )


def _guaranteed_store_one_day_into_a_two_stage_cadence():
    """A GUARANTEED engagement whose single store has both variants populated.

    Five thousand cents of original cost across 1,200 units, a two-stage cadence
    at 0.20 and 0.40, and exactly one posted selling day of 1,200,000 cents on
    300 units.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(
        code="NY", name="New York", gob_license_required=True, max_sale_days=60,
        license_cooling_off_days=30, max_augmentation_ratio=0.1,
        augmentation_disclosure_required=True, advertising_disclosure_required=False,
        surrender_notice_days=10, prohibited_claim_codes=["LOWEST_PRICES_EVER"],
    )
    engagement = create_engagement(
        economics_model="GUARANTEED", guaranty_pct=1.5, hybrid_retailer_excess_pct=0,
        expense_responsibility="SHARED", shared_expense_liquidator_pct=0.4,
        sale_start_date="2026-09-15", target_end_date="2026-11-30",
    )
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-101", address_line="12 Main St",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0001",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    stage_one = add_markdown_stage(
        store["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    stage_two = add_markdown_stage(
        store["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    activate_markdown_stage(stage_one["id"])
    pin_clock("2026-09-20T00:00:00Z")
    _post_day(store)
    return {
        "engagement": engagement,
        "store": read_store(store["id"]),
        "stages": [stage_one, stage_two],
    }


class TestRecoveryDuality:
    def test_recovery_summary_reports_every_declared_figure(self):
        """Both variants sit side by side in the recovery read.

        The PRD says: "It returns `projected_gross_recovery_cents`,
        `projected_recovery_ratio`, `realized_gross_recovery_cents`,
        `realized_recovery_ratio`, `planned_avg_discount_pct`,
        `projected_shortfall_cents`, `guaranty_amount_cents`,
        `original_cost_value_cents`, and `store_count`, the number of stores in
        the engagement."

        Design: Difficulty/dual_variant_calc/store_recovery_projected_vs_realized_diverge_on_one_store
        """
        scenario = _guaranteed_store_one_day_into_a_two_stage_cadence()
        summary = validate_success(
            api_client.get_recovery_summary(
                scenario["engagement"]["id"], make_controller_headers()
            )
        )
        assert_recovery_summary(summary)
        assert summary["planned_avg_discount_pct"] == pytest.approx(0.3000, abs=0.00001)
        assert summary["projected_gross_recovery_cents"] == 6965000
        assert summary["projected_recovery_ratio"] == pytest.approx(1.3930, abs=0.00001)
        assert summary["realized_gross_recovery_cents"] == 1200000
        assert summary["realized_recovery_ratio"] == pytest.approx(0.2400, abs=0.00001)
        assert summary["original_cost_value_cents"] == 5000000
        assert summary["guaranty_amount_cents"] == 7500000
        assert summary["projected_shortfall_cents"] == 535000
        assert summary["store_count"] == 1

    def test_the_two_variants_disagree_on_the_same_stored_data(self):
        """A projected ratio far above 1.0 alongside a realized ratio near 0.2.

        The PRD says: "The two variants are expected to disagree, and sharply: a
        store one day into a two-stage cadence will show a projected ratio well
        above 1.0 while its realized ratio still sits near 0.2."

        Design: Difficulty/dual_variant_calc/store_recovery_projected_vs_realized_diverge_on_one_store
        """
        scenario = _guaranteed_store_one_day_into_a_two_stage_cadence()
        summary = validate_success(
            api_client.get_recovery_summary(
                scenario["engagement"]["id"], make_controller_headers()
            )
        )
        assert summary["projected_gross_recovery_cents"] != \
            summary["realized_gross_recovery_cents"]
        assert summary["projected_recovery_ratio"] > 1.0
        assert summary["realized_recovery_ratio"] == pytest.approx(0.2400, abs=0.00001)
        store = scenario["store"]
        assert store["projected_gross_recovery_cents"] == 6965000
        assert store["projected_recovery_ratio"] == pytest.approx(1.3930, abs=0.00001)
        assert store["realized_gross_recovery_cents"] == 1200000
        assert store["realized_recovery_ratio"] == pytest.approx(0.2400, abs=0.00001)

    def test_realized_sell_through_counts_only_the_posted_units(self):
        """Three hundred units sold out of 1,200 on the floor reads 0.2500.

        The PRD says: "Its `units_sold_total` is the sum of `units_sold` across
        all its lots, and `realized_sell_through_pct` is that total divided by
        `units_initial_total`, rounded half up to four decimal places and exactly
        0.0000 when `units_initial_total` is 0."

        Design: Difficulty/dual_variant_calc/store_recovery_projected_vs_realized_diverge_on_one_store
        """
        scenario = _guaranteed_store_one_day_into_a_two_stage_cadence()
        store = scenario["store"]
        assert store["units_initial_total"] == 1200
        assert store["units_sold_total"] == 300
        assert store["realized_sell_through_pct"] == pytest.approx(0.2500, abs=0.00001)
        assert store["planned_avg_discount_pct"] == pytest.approx(0.3000, abs=0.00001)
