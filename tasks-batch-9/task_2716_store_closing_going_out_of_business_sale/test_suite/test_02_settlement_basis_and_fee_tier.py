"""Settlement worksheets: the basis inclusion sets and the pinned fee tier order.

Two worksheets over one engagement disagree because the basis changes which
selling days and which expense items are in scope, and a single worksheet keys
its fee tier on original-merchandise recovery while charging the fee on total
gross recovery.
"""
import pytest

from test_helpers import (
    add_inventory_lot,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    approve_expense_item,
    assert_settlement,
    assert_settlement_closing_identity,
    close_store,
    create_engagement,
    create_jurisdiction,
    decide_license,
    file_consignment_disclosure,
    file_sales_day,
    make_consultant_headers,
    make_controller_headers,
    open_settlement,
    pin_clock,
    post_sales_day,
    propose_consignment,
    propose_settlement,
    receive_consignment,
    setup_proposed_settlement,
    submit_engagement,
    submit_expense_item,
    validate_paginated,
    validate_success,
    wind_down_engagement,
)

APPAREL_LOT = {
    "category": "APPAREL", "source": "ORIGINAL", "units_initial": 1000,
    "unit_cost_cents": 2000, "unit_retail_cents": 5000,
}
ELECTRONICS_LOT = {
    "category": "ELECTRONICS", "source": "ORIGINAL", "units_initial": 200,
    "unit_cost_cents": 15000, "unit_retail_cents": 30000,
}
NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
SHARED_FEE_BASED = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "SHARED",
    "shared_expense_liquidator_pct": 0.4, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}


def _read_settlement(settlement_id):
    return validate_success(
        api_client.get_settlement(settlement_id, make_controller_headers())
    )


def _two_bases_over_one_engagement():
    """One engagement carrying a superseded PROVISIONAL and an open FINAL.

    The ledger holds two posted days, one day still in review, one approved
    expense and one still-submitted expense, so the two bases see different
    inclusion sets over identical stored facts.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**SHARED_FEE_BASED)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-201", address_line="44 Elm St",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0201",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    pin_clock("2026-09-20T00:00:00Z")
    consignment = propose_consignment(
        store["id"], supplier_name="Northline Supply", category="APPAREL",
        units_supplied=200, unit_cost_cents=2000, unit_retail_cents=5000,
        delivery_window_start_date="2026-09-16",
        delivery_window_end_date="2026-09-18",
    )
    file_consignment_disclosure(consignment["id"], "NY-AUG-77")
    receive_consignment(consignment["id"])
    post_sales_day(
        store["id"], business_date="2026-09-16",
        original_net_sales_cents=1800000, augmentation_net_sales_cents=0,
        original_units_sold=400, augmentation_units_sold=0,
    )
    post_sales_day(
        store["id"], business_date="2026-09-17",
        original_net_sales_cents=2400000, augmentation_net_sales_cents=600000,
        original_units_sold=500, augmentation_units_sold=150,
    )
    pending_day = file_sales_day(
        store["id"], business_date="2026-09-18",
        original_net_sales_cents=400000, augmentation_net_sales_cents=0,
        original_units_sold=100, augmentation_units_sold=0,
    )
    approved_expense = submit_expense_item(
        engagement["id"], store_id=store["id"], expense_category="OCCUPANCY",
        amount_cents=250000, incurred_date="2026-09-16",
    )
    approve_expense_item(approved_expense["id"])
    submitted_expense = submit_expense_item(
        engagement["id"], store_id=store["id"], expense_category="ADVERTISING",
        amount_cents=100000, incurred_date="2026-09-17",
    )
    provisional = setup_proposed_settlement(engagement["id"], "PROVISIONAL")
    close_store(store["id"])
    wind_down_engagement(engagement["id"])
    final = open_settlement(engagement["id"], "FINAL", supersede_open=True)
    final = propose_settlement(final["id"])
    return {
        "engagement": engagement,
        "store": store,
        "provisional": _read_settlement(provisional["id"]),
        "final": final,
        "pending_day": pending_day,
        "approved_expense": approved_expense,
        "submitted_expense": submitted_expense,
    }


class TestSettlementBasisDuality:
    def test_provisional_basis_pulls_in_the_day_in_review_and_the_submitted_expense(self):
        """The wider inclusion set lifts gross recovery and the expense total.

        The PRD says: "Under `PROVISIONAL` the day set additionally includes days
        still `PENDING_REVIEW` and the expense set additionally includes items
        still `SUBMITTED`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_basis_diverge_on_one_engagement
        """
        scenario = _two_bases_over_one_engagement()
        provisional = scenario["provisional"]
        assert_settlement(provisional)
        assert provisional["settlement_status"] == "SUPERSEDED"
        assert provisional["gross_recovery_cents"] == 5200000
        assert provisional["original_net_sales_cents"] == 4600000
        assert provisional["recovery_ratio"] == pytest.approx(0.9200, abs=0.00001)
        assert provisional["fee_rate"] == pytest.approx(0.0500, abs=0.00001)
        assert provisional["liquidator_fee_cents"] == 260000
        assert provisional["expense_total_cents"] == 350000
        assert provisional["liquidator_expense_cents"] == 140000
        assert provisional["retailer_expense_cents"] == 210000
        assert provisional["retailer_proceeds_cents"] == 4730000
        assert provisional["liquidator_proceeds_cents"] == 120000
        assert_settlement_closing_identity(provisional)

    def test_final_basis_admits_only_the_posted_days_and_the_approved_expense(self):
        """The narrower inclusion set produces a different split on the same books.

        The PRD says: "Under `FINAL` the day set is the engagement's selling days
        whose `day_status` is `POSTED` and the expense set is its items whose
        `expense_status` is `APPROVED` or `SETTLED`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_basis_diverge_on_one_engagement
        """
        scenario = _two_bases_over_one_engagement()
        final = scenario["final"]
        assert_settlement(final)
        assert final["settlement_status"] == "PROPOSED"
        assert final["gross_recovery_cents"] == 4800000
        assert final["original_net_sales_cents"] == 4200000
        assert final["recovery_ratio"] == pytest.approx(0.8400, abs=0.00001)
        assert final["fee_rate"] == pytest.approx(0.0500, abs=0.00001)
        assert final["liquidator_fee_cents"] == 240000
        assert final["expense_total_cents"] == 250000
        assert final["liquidator_expense_cents"] == 100000
        assert final["retailer_expense_cents"] == 150000
        assert final["retailer_proceeds_cents"] == 4410000
        assert final["liquidator_proceeds_cents"] == 140000
        assert_settlement_closing_identity(final)

    def test_the_two_bases_disagree_while_the_excluded_rows_stay_where_they_were(self):
        """The day in review and the submitted expense are untouched by either basis.

        The PRD says: "Filing moves no inventory and no ledger figure whatsoever —
        nothing happens to units or money until the retailer posts the day."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_basis_diverge_on_one_engagement
        """
        scenario = _two_bases_over_one_engagement()
        provisional, final = scenario["provisional"], scenario["final"]
        assert provisional["gross_recovery_cents"] != final["gross_recovery_cents"]
        assert provisional["original_net_sales_cents"] != final["original_net_sales_cents"]
        assert provisional["expense_total_cents"] != final["expense_total_cents"]
        assert provisional["retailer_proceeds_cents"] != final["retailer_proceeds_cents"]
        rows, _meta = validate_paginated(
            api_client.list_sales_days(
                scenario["store"]["id"], make_consultant_headers(),
                {"day_status": "PENDING_REVIEW"},
            )
        )
        assert [row["business_date"] for row in rows] == ["2026-09-18"]
        assert rows[0]["id"] == scenario["pending_day"]["id"]
        submitted = validate_success(
            api_client.get_expense_item(
                scenario["submitted_expense"]["id"], make_consultant_headers()
            )
        )
        assert submitted["expense_status"] == "SUBMITTED"


def _engagement_whose_tier_and_fee_bases_differ():
    """A ledger where the original ratio and the total-gross ratio fall in
    different fee bands.

    Original-merchandise recovery is 3,900,000 against 5,000,000 of original
    cost, so the ratio is 0.7800 and sits in the middle band, while total gross
    recovery including augmentation is 4,200,000.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**SHARED_FEE_BASED)
    store = add_store(
        engagement["id"], jurisdiction["id"],
        store_code="S-301", address_line="7 Canal St",
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0301",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    pin_clock("2026-09-20T00:00:00Z")
    consignment = propose_consignment(
        store["id"], supplier_name="Northline Supply", category="APPAREL",
        units_supplied=200, unit_cost_cents=2000, unit_retail_cents=5000,
        delivery_window_start_date="2026-09-16",
        delivery_window_end_date="2026-09-18",
    )
    file_consignment_disclosure(consignment["id"], "NY-AUG-81")
    receive_consignment(consignment["id"])
    post_sales_day(
        store["id"], business_date="2026-09-16",
        original_net_sales_cents=1800000, augmentation_net_sales_cents=0,
        original_units_sold=400, augmentation_units_sold=0,
    )
    post_sales_day(
        store["id"], business_date="2026-09-17",
        original_net_sales_cents=2100000, augmentation_net_sales_cents=300000,
        original_units_sold=500, augmentation_units_sold=100,
    )
    worksheet = open_settlement(engagement["id"], "PROVISIONAL")
    return {
        "engagement": engagement,
        "store": store,
        "settlement": propose_settlement(worksheet["id"]),
    }


class TestFeeTierEvaluationOrder:
    def test_the_tier_is_keyed_on_original_recovery_and_not_on_total_gross(self):
        """A 0.7800 original ratio draws the middle band even though total gross
        recovery would reach 0.8400.

        The PRD says: "The `fee_rate` is then selected from the ratio by a
        three-band tier table: a ratio below 0.60 draws 0.0200, a ratio from 0.60
        up to but excluding 0.80 draws 0.0350, and a ratio of 0.80 or more draws
        0.0500."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_evaluation_order_original_ratio_then_total_gross
        """
        settlement = _engagement_whose_tier_and_fee_bases_differ()["settlement"]
        assert_settlement(settlement)
        assert settlement["original_net_sales_cents"] == 3900000
        assert settlement["gross_recovery_cents"] == 4200000
        assert settlement["recovery_ratio"] == pytest.approx(0.7800, abs=0.00001)
        assert settlement["fee_rate"] == pytest.approx(0.0350, abs=0.00001)
        assert settlement["fee_rate"] != pytest.approx(0.0500, abs=0.00001)

    def test_the_fee_is_charged_on_total_gross_recovery_including_augmentation(self):
        """The middle-band rate applied to 4,200,000 is 147,000 cents.

        The PRD says: "the tier is keyed on original-merchandise recovery, while
        the fee is charged on total gross recovery including augmentation."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_evaluation_order_original_ratio_then_total_gross
        """
        settlement = _engagement_whose_tier_and_fee_bases_differ()["settlement"]
        assert settlement["liquidator_fee_cents"] == 147000
        assert settlement["liquidator_fee_cents"] != 210000
        assert settlement["expense_total_cents"] == 0
        assert settlement["liquidator_expense_cents"] == 0
        assert settlement["retailer_expense_cents"] == 0
        assert settlement["retailer_proceeds_cents"] == 4053000
        assert settlement["liquidator_proceeds_cents"] == 147000

    def test_the_closing_identity_holds_over_the_tiered_fee(self):
        """Retailer plus liquidator plus expenses come back to gross recovery.

        The PRD says: "The conserved quantity is stated as an invariant that must
        hold exactly under every model and every basis, with no rounding
        tolerance: the retailer's proceeds plus the liquidator's proceeds plus the
        total expense equal the gross recovery."

        Design: Difficulty/combinatorial_formula/settlement_fee_tier_evaluation_order_original_ratio_then_total_gross
        """
        settlement = _engagement_whose_tier_and_fee_bases_differ()["settlement"]
        assert_settlement_closing_identity(settlement)
        assert (
            settlement["retailer_proceeds_cents"]
            + settlement["liquidator_proceeds_cents"]
            + settlement["expense_total_cents"]
        ) == 4200000
