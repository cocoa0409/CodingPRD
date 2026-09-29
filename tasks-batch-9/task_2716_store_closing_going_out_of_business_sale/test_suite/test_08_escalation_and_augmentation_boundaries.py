"""Two boundaries, each approached from both sides.

A checkpoint shortfall of exactly zero must not escalate while the smallest
positive shortfall costs one whole band; an augmentation ratio of exactly the cap
must be received while eight ten-thousandths past it must not.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_markdown_stage,
    add_inventory_lot,
    add_markdown_stage,
    add_store,
    api_client,
    apply_for_license,
    approve_engagement,
    assert_inventory_lot,
    assert_markdown_stage,
    assert_recovery_summary,
    checkpoint_markdown_stage,
    create_engagement,
    create_jurisdiction,
    decide_license,
    file_consignment_disclosure,
    make_consultant_headers,
    make_controller_headers,
    pin_clock,
    post_sales_day,
    propose_consignment,
    read_store,
    receive_consignment,
    submit_engagement,
    validate_error,
    validate_paginated,
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
NY_RULES = {
    "code": "NY", "name": "New York", "gob_license_required": True,
    "max_sale_days": 60, "license_cooling_off_days": 30,
    "max_augmentation_ratio": 0.1, "augmentation_disclosure_required": True,
    "advertising_disclosure_required": False, "surrender_notice_days": 10,
}
FEE_BASED_LIQUIDATOR = {
    "economics_model": "FEE_BASED", "guaranty_pct": 0,
    "hybrid_retailer_excess_pct": 0, "expense_responsibility": "LIQUIDATOR",
    "shared_expense_liquidator_pct": 0, "sale_start_date": "2026-09-15",
    "target_end_date": "2026-11-30",
}


def _read_stage(stage_id):
    return validate_success(
        api_client.get_markdown_stage(stage_id, make_consultant_headers())
    )


def _read_consignment(consignment_id):
    return validate_success(
        api_client.get_augmentation_consignment(
            consignment_id, make_consultant_headers()
        )
    )


def _store_with_the_standard_two_lots(
    engagement_id, jurisdiction_id, store_code, address
):
    store = add_store(
        engagement_id, jurisdiction_id, store_code=store_code, address_line=address,
    )
    add_inventory_lot(store["id"], **APPAREL_LOT)
    add_inventory_lot(store["id"], **ELECTRONICS_LOT)
    return store


def _two_stores_checkpointed_either_side_of_a_zero_shortfall():
    """Identical stores, identical sales, targets 0.25 and 0.30.

    Both stores realize a sell-through of exactly 0.2500, so the first store's
    shortfall is exactly 0.0000 and the second's is 0.0500 — the smallest shortfall
    that still buys a whole escalation band.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store_a = _store_with_the_standard_two_lots(
        engagement["id"], jurisdiction["id"], "S-201", "1 Elm St",
    )
    store_b = _store_with_the_standard_two_lots(
        engagement["id"], jurisdiction["id"], "S-202", "2 Elm St",
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    for store, number in ((store_a, "NY-GOB-0201"), (store_b, "NY-GOB-0202")):
        license_row = apply_for_license(
            store["id"], license_number=number,
            period_start_date="2026-09-15", period_end_date="2026-10-14",
            advertising_claim_codes=["EVERYTHING_MUST_GO"],
        )
        decide_license(license_row["id"])
    stage_a1 = add_markdown_stage(
        store_a["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.25,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    stage_a2 = add_markdown_stage(
        store_a["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    stage_b1 = add_markdown_stage(
        store_b["id"], stage_index=1, discount_pct=0.2, sell_through_target_pct=0.3,
        window_start_date="2026-09-15", window_end_date="2026-09-29",
    )
    stage_b2 = add_markdown_stage(
        store_b["id"], stage_index=2, discount_pct=0.4, sell_through_target_pct=0.6,
        window_start_date="2026-09-29", window_end_date="2026-10-13",
    )
    activate_markdown_stage(stage_a1["id"])
    activate_markdown_stage(stage_b1["id"])
    pin_clock("2026-09-20T00:00:00Z")
    for store in (store_a, store_b):
        post_sales_day(
            store["id"], business_date="2026-09-16",
            original_net_sales_cents=1200000, augmentation_net_sales_cents=0,
            original_units_sold=300, augmentation_units_sold=0,
        )
    checkpoint_markdown_stage(stage_a1["id"])
    checkpoint_markdown_stage(stage_b1["id"])
    summary = validate_success(
        api_client.get_recovery_summary(engagement["id"], make_controller_headers())
    )
    return {
        "engagement": engagement,
        "store_a": read_store(store_a["id"]),
        "store_b": read_store(store_b["id"]),
        "stage_a1": _read_stage(stage_a1["id"]),
        "stage_a2": _read_stage(stage_a2["id"]),
        "stage_b1": _read_stage(stage_b1["id"]),
        "stage_b2": _read_stage(stage_b2["id"]),
        "summary": summary,
    }


class TestCheckpointShortfallZeroBoundary:
    def test_a_shortfall_of_exactly_zero_closes_the_stage_on_schedule(self):
        """Target 0.2500 met exactly: no escalation and the successor untouched.

        The PRD says: "When the shortfall is zero or negative — meaning the store
        met or beat its target — the stage's `escalation_applied_pct` is exactly
        0.0000, its `closed_reason` is `ON_SCHEDULE`, and the following stage's
        discount is left entirely alone."

        Design: Difficulty/boundary_precision_check/checkpoint_shortfall_exactly_zero_versus_one_band_short
        """
        scenario = _two_stores_checkpointed_either_side_of_a_zero_shortfall()
        assert scenario["store_a"]["realized_sell_through_pct"] == pytest.approx(
            0.2500, abs=0.00001
        )
        stage_a1 = scenario["stage_a1"]
        assert_markdown_stage(stage_a1)
        assert stage_a1["stage_status"] == "CLOSED"
        assert stage_a1["closed_reason"] == "ON_SCHEDULE"
        assert stage_a1["escalation_applied_pct"] == pytest.approx(0.0, abs=0.00001)
        assert stage_a1["checkpoint_sell_through_pct"] == pytest.approx(
            0.2500, abs=0.00001
        )
        stage_a2 = scenario["stage_a2"]
        assert stage_a2["stage_status"] == "ARMED"
        assert stage_a2["discount_pct"] == pytest.approx(0.4000, abs=0.00001)

    def test_the_smallest_positive_shortfall_still_costs_one_whole_band(self):
        """A shortfall of 0.0500 rounds up to one step of 0.05 on the successor.

        The PRD says: "When the shortfall is positive, the number of escalation
        steps is the shortfall divided by an escalation band of 0.05 and rounded up
        to a whole number, so any shortfall up to five percentage points is one
        step, anything above five and up to ten is two steps, and so on; at least
        one step always results."

        Design: Difficulty/boundary_precision_check/checkpoint_shortfall_exactly_zero_versus_one_band_short
        """
        scenario = _two_stores_checkpointed_either_side_of_a_zero_shortfall()
        assert scenario["store_b"]["realized_sell_through_pct"] == pytest.approx(
            0.2500, abs=0.00001
        )
        stage_b1 = scenario["stage_b1"]
        assert stage_b1["closed_reason"] == "ESCALATED"
        assert stage_b1["escalation_applied_pct"] == pytest.approx(0.0500, abs=0.00001)
        assert stage_b1["checkpoint_sell_through_pct"] == pytest.approx(
            0.2500, abs=0.00001
        )
        stage_b2 = scenario["stage_b2"]
        assert stage_b2["stage_status"] == "ARMED"
        assert stage_b2["discount_pct"] == pytest.approx(0.4500, abs=0.00001)

    def test_the_two_branches_move_the_projections_apart(self):
        """The escalated successor drags its store's projection below the other's.

        The PRD says: "The checkpoint finishes by recomputing the store's
        `planned_avg_discount_pct`, its projected recovery figures, and the
        engagement roll-up, and by incrementing the stage's `version`."

        Design: Difficulty/boundary_precision_check/checkpoint_shortfall_exactly_zero_versus_one_band_short
        """
        scenario = _two_stores_checkpointed_either_side_of_a_zero_shortfall()
        store_a, store_b = scenario["store_a"], scenario["store_b"]
        assert store_a["planned_avg_discount_pct"] == pytest.approx(0.4000, abs=0.00001)
        assert store_a["projected_gross_recovery_cents"] == 5970000
        assert store_a["projected_recovery_ratio"] == pytest.approx(1.1940, abs=0.00001)
        assert store_b["planned_avg_discount_pct"] == pytest.approx(0.4500, abs=0.00001)
        assert store_b["projected_gross_recovery_cents"] == 5472500
        assert store_b["projected_recovery_ratio"] == pytest.approx(1.0945, abs=0.00001)

    def test_the_engagement_rolls_up_both_stores_and_reports_no_shortfall(self):
        """11,442,500 projected across the two stores against no guaranty at all.

        The PRD says: "At the engagement level the projection rolls up:
        `projected_gross_recovery_cents` is the sum of the same field over every
        store of the engagement, and `projected_shortfall_cents` is the guaranty
        amount less that projected gross recovery, floored at 0 so that a projection
        which clears the guaranty reports no shortfall at all."

        Design: Difficulty/boundary_precision_check/checkpoint_shortfall_exactly_zero_versus_one_band_short
        """
        scenario = _two_stores_checkpointed_either_side_of_a_zero_shortfall()
        summary = scenario["summary"]
        assert_recovery_summary(summary)
        assert summary["projected_gross_recovery_cents"] == 11442500
        assert summary["projected_shortfall_cents"] == 0
        assert summary["store_count"] == 2


def _store_taken_exactly_to_the_augmentation_cap():
    """500,000 cents of consigned goods against a 5,000,000-cent original base.

    The first consignment lands the post-receipt ratio on exactly 0.1000, and the
    second offers a further 4,000 cents, which is only eight ten-thousandths of the
    base but still past an inclusive cap.
    """
    pin_clock("2026-09-15T00:00:00Z")
    jurisdiction = create_jurisdiction(**NY_RULES)
    engagement = create_engagement(**FEE_BASED_LIQUIDATOR)
    store = _store_with_the_standard_two_lots(
        engagement["id"], jurisdiction["id"], "S-301", "9 Canal St",
    )
    submit_engagement(engagement["id"])
    approve_engagement(engagement["id"])
    license_row = apply_for_license(
        store["id"], license_number="NY-GOB-0301",
        period_start_date="2026-09-15", period_end_date="2026-10-14",
        advertising_claim_codes=["EVERYTHING_MUST_GO"],
    )
    decide_license(license_row["id"])
    consignment_x = propose_consignment(
        store["id"], supplier_name="Overstock Partners", category="APPAREL",
        units_supplied=250, unit_cost_cents=2000, unit_retail_cents=5000,
        delivery_window_start_date="2026-09-20",
        delivery_window_end_date="2026-09-21",
    )
    file_consignment_disclosure(consignment_x["id"], "NY-AUG-201")
    consignment_y = propose_consignment(
        store["id"], supplier_name="Overstock Partners", category="APPAREL",
        units_supplied=2, unit_cost_cents=2000, unit_retail_cents=5000,
        delivery_window_start_date="2026-09-22",
        delivery_window_end_date="2026-09-23",
    )
    file_consignment_disclosure(consignment_y["id"], "NY-AUG-202")
    received_x = receive_consignment(consignment_x["id"])
    refusal_y = api_client.receive_consignment(
        consignment_y["id"], make_consultant_headers()
    )
    return {
        "engagement": engagement,
        "store": read_store(store["id"]),
        "consignment_x": received_x,
        "consignment_y": consignment_y,
        "refusal_y": refusal_y,
    }


class TestAugmentationRatioCapBoundary:
    def test_a_post_receipt_ratio_of_exactly_the_cap_is_accepted(self):
        """500,000 over 5,000,000 is 0.1000, which the cap admits.

        The PRD says: "The comparison is inclusive at the cap: a post-receipt ratio
        exactly equal to the jurisdiction's `max_augmentation_ratio` is accepted, and
        only a ratio strictly greater than it is refused, with
        `ERR_AUGMENTATION_CAP_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/augmentation_ratio_exactly_at_cap_accepted_then_eight_ten_thousandths_over_rejected
        """
        scenario = _store_taken_exactly_to_the_augmentation_cap()
        assert scenario["consignment_x"]["consignment_status"] == "RECEIVED"
        store = scenario["store"]
        assert store["augmentation_cost_value_cents"] == 500000
        assert store["original_cost_value_cents"] == 5000000

    def test_the_accepted_receipt_creates_the_lot_and_moves_the_unit_counts(self):
        """1,450 initial units on the floor with 250 of them accounted as consigned.

        The PRD says: "The store's `augmentation_cost_value_cents`,
        `units_initial_total`, `augmentation_units_accounted`, and
        `realized_sell_through_pct` are recomputed, followed by the store's projected
        recovery figures and the engagement roll-up; the store's
        `original_cost_value_cents` is pointedly not touched, because consigned goods
        are not the retailer's own cost."

        Design: Difficulty/boundary_precision_check/augmentation_ratio_exactly_at_cap_accepted_then_eight_ten_thousandths_over_rejected
        """
        scenario = _store_taken_exactly_to_the_augmentation_cap()
        store = scenario["store"]
        assert store["units_initial_total"] == 1450
        assert store["augmentation_units_accounted"] == 250
        assert store["projected_gross_recovery_cents"] == 11010000
        assert store["projected_recovery_ratio"] == pytest.approx(2.2020, abs=0.00001)
        lots, _meta = validate_paginated(
            api_client.list_consignment_inventory_lots(
                scenario["consignment_x"]["id"], make_consultant_headers()
            )
        )
        assert len(lots) == 1
        assert_inventory_lot(lots[0])
        assert lots[0]["source"] == "AUGMENTATION"
        assert lots[0]["units_initial"] == 250
        assert lots[0]["units_on_hand"] == 250

    def test_four_thousand_cents_past_the_cap_is_refused(self):
        """A post-receipt ratio of 0.1008 is strictly greater than 0.1000.

        The PRD says: "Sum the `cost_value_cents` of every consignment of the store
        whose status is `RECEIVED` or `SOLD_OUT`; those count at full cost value."

        Design: Difficulty/boundary_precision_check/augmentation_ratio_exactly_at_cap_accepted_then_eight_ten_thousandths_over_rejected
        """
        scenario = _store_taken_exactly_to_the_augmentation_cap()
        validate_error(
            scenario["refusal_y"], ApiErrorId.ERR_AUGMENTATION_CAP_EXCEEDED.value, 422
        )
        consignment_y = _read_consignment(scenario["consignment_y"]["id"])
        assert consignment_y["consignment_status"] == "DISCLOSURE_FILED"
        lots, _meta = validate_paginated(
            api_client.list_consignment_inventory_lots(
                scenario["consignment_y"]["id"], make_consultant_headers()
            )
        )
        assert lots == []
        store = scenario["store"]
        assert store["augmentation_cost_value_cents"] == 500000
        assert store["units_initial_total"] == 1450
