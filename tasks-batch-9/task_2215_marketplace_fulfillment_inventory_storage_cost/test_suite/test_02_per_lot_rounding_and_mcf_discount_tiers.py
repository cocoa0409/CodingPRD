"""Multi-input formulas whose pinned rounding order and pinned tier key change the
answer: per-lot storage rounding, and the pre-discount volume tier."""
import pytest

from test_helpers import (
    add_line_item,
    api_client,
    assert_multi_channel_order,
    assert_storage_fee_assessment,
    confirm_plan,
    create_listing,
    create_plan,
    first_lot_for_listing,
    place_multi_channel_order,
    read_lot,
    read_seller,
    receive_plan,
    run_storage_billing,
    setup_baseline,
    ship_plan,
    validate_paginated,
)


def _two_lots_of_fractional_volume() -> dict:
    """One received unit of a 0.5831 cubic-foot SKU and one of a 0.9163 cubic-foot SKU,
    each in its own lot at a centre charging 87 cents per cubic foot."""
    ctx = setup_baseline(with_listing=False)
    listing_a = create_listing(ctx["seller_id"], sku="SKU-CF-A", unit_cubic_feet=0.5831)
    listing_b = create_listing(ctx["seller_id"], sku="SKU-CF-B", unit_cubic_feet=0.9163)
    plan = create_plan(
        ctx["seller_id"], ctx["fc_id"], "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"
    )
    line_a = add_line_item(
        plan["id"], ctx["seller_id"], listing_a["id"], 1, case_pack_units=1
    )
    line_b = add_line_item(
        plan["id"], ctx["seller_id"], listing_b["id"], 1, case_pack_units=1
    )
    confirm_plan(plan["id"], ctx["seller_id"])
    ship_plan(plan["id"], ctx["seller_id"], carrier_reference="CR-1")
    receive_plan(
        plan["id"], ctx["fc_id"], [(line_a["id"], 1, 0), (line_b["id"], 1, 0)]
    )
    ctx.update({
        "listing_a": listing_a,
        "listing_b": listing_b,
        "lot_a": first_lot_for_listing(listing_a["id"], ctx["seller_id"]),
        "lot_b": first_lot_for_listing(listing_b["id"], ctx["seller_id"]),
    })
    return ctx


def _assessments(lot_id: str, headers) -> list:
    rows, _meta = validate_paginated(
        api_client.list_storage_fee_assessments(lot_id, headers)
    )
    return rows


class TestStorageFeePerLotRounding:
    """Rounding each lot first and summing afterwards is worth one cent here."""

    def test_two_fractional_lots_assess_131_cents_rather_than_130(self):
        """0.5831 and 0.9163 cubic feet at 87 cents give 51 plus 80 under per-lot
        rounding, and the run total must be that 131 rather than the combined 130.

        PRD 3.9: "Summing raw cubic feet across lots and rounding once at the end is a
        different and forbidden result: two lots holding 0.5831 and 0.9163 cubic feet at a
        rate of 87 cents per cubic foot give 51 plus 80, or 131 cents, under per-lot
        rounding, whereas rounding the combined 1.4994 cubic feet once gives 130 cents."

        Design: Difficulty/combinatorial_formula/storage_fee_per_lot_rounding_beats_sum_then_round_by_one_cent
        """
        _two_lots_of_fractional_volume()
        summary = run_storage_billing(run_note="epoch 1")
        assert summary["billing_run_sequence"] == 1
        assert summary["assessment_count"] == 2
        assert summary["total_assessed_cents"] == 131
        assert summary["total_assessed_cents"] != 130

    def test_each_assessment_row_carries_its_own_rounded_volume_and_fee(self):
        """The smaller lot bills 51 cents and the larger 80, with no long-term surcharge
        at zero age, and each lot accrues exactly its own row.

        PRD 3.9: "`billable_cubic_feet` is that count multiplied by the listing's
        `unit_cubic_feet`, rounded to four decimal places. `monthly_storage_fee_cents` is
        `billable_cubic_feet` multiplied by the holding centre's
        `monthly_storage_rate_cents_per_cubic_foot`, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/storage_fee_per_lot_rounding_beats_sum_then_round_by_one_cent
        """
        ctx = _two_lots_of_fractional_volume()
        run_storage_billing(run_note="epoch 1")

        row_a = _assessments(ctx["lot_a"]["id"], ctx["seller_headers"])[0]
        assert_storage_fee_assessment(row_a)
        assert float(row_a["billable_cubic_feet"]) == pytest.approx(0.5831, abs=1e-4)
        assert row_a["monthly_storage_fee_cents"] == 51
        assert row_a["ltsf_surcharge_cents"] == 0
        assert row_a["total_fee_cents"] == 51

        row_b = _assessments(ctx["lot_b"]["id"], ctx["seller_headers"])[0]
        assert float(row_b["billable_cubic_feet"]) == pytest.approx(0.9163, abs=1e-4)
        assert row_b["monthly_storage_fee_cents"] == 80
        assert row_b["total_fee_cents"] == 80

        assert read_lot(ctx["lot_a"]["id"], ctx["seller_id"])["storage_fee_accrued_cents"] == 51
        assert read_lot(ctx["lot_b"]["id"], ctx["seller_id"])["storage_fee_accrued_cents"] == 80

    def test_seller_ledger_and_utilization_follow_the_per_lot_integers(self):
        """The seller accrues the summed per-lot integers, and 1.4994 cubic feet against a
        1000 cubic-foot entitlement rounds to a utilization of 0.0015.

        PRD 3.9: "Each lot's `monthly_storage_fee_cents` and `ltsf_surcharge_cents` are
        rounded half up to whole cents **first**, then added together per lot, then the
        per-lot integers are summed into the lot's `storage_fee_accrued_cents` and into the
        seller's `storage_fee_accrued_cents`."
        PRD 3.9: "The seller's `storage_utilization_ratio` is that total divided by the
        seller's `storage_cubic_feet_entitlement`, rounded half up to four decimal places."

        Design: Difficulty/combinatorial_formula/storage_fee_per_lot_rounding_beats_sum_then_round_by_one_cent
        """
        ctx = _two_lots_of_fractional_volume()
        summary = run_storage_billing(run_note="epoch 1")
        assert summary["downgraded_quota_count"] == 0
        assert summary["expired_quota_count"] == 0
        assert summary["closed_plan_count"] == 0

        seller = read_seller(ctx["seller_id"])
        assert seller["storage_fee_accrued_cents"] == 131
        assert float(seller["storage_utilization_ratio"]) == pytest.approx(
            0.0015, abs=1e-4
        )


class TestMcfVolumeDiscountTierKey:
    """The discount tier is keyed on the pre-discount total, never on the net fee."""

    def test_forty_units_reach_the_three_percent_tier_on_the_pre_discount_total(self):
        """A 20000-cent pre-discount total earns the 3 percent tier and nets 19400 cents,
        an exact tie against the seller's own cost that resolves to MCF.

        PRD 3.7: "The volume discount tier is keyed on that **pre-discount** total and
        never on the discounted figure: ten percent when the pre-discount total is at least
        100000 cents, six percent when it is at least 50000 cents, three percent when it is
        at least 20000 cents, and zero otherwise."
        PRD 3.7: "`fee_advantage_cents` is `self_fulfilled_cost_cents` minus
        `mcf_fee_cents`, and `recommended_channel` is `MCF` when that advantage is at least
        0 and `SELF_FULFILLED` when it is negative — an exact tie of zero resolves to
        `MCF`."

        Design: Difficulty/combinatorial_formula/mcf_volume_discount_tier_keyed_on_pre_discount_total
        """
        ctx = setup_baseline()
        order = place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 40, 2.00, "ZONE_2",
            "SELF_FULFILLED", 19400,
        )
        assert_multi_channel_order(order)
        assert order["is_peak_period"] is False
        assert order["mcf_fee_cents"] == 19400
        assert order["fee_advantage_cents"] == 0
        assert order["recommended_channel"] == "MCF"
        assert order["order_status"] == "SELF_SHIPPED"
        assert order["consumed_lot_allocations"] == []

    def test_one_unit_fewer_falls_below_the_tier_and_costs_more(self):
        """39 units give a 19500-cent pre-discount total, below the 20000-cent threshold,
        so the undiscounted fee exceeds the discounted fee of the larger order.

        PRD 3.7: "Keying the tier on the post-discount total is circular and drops a tier
        at the boundaries; that reading is forbidden."
        PRD 3.7: "The per-unit fee is that base plus an overweight component: the amount by
        which `billable_weight_lb` exceeds one pound — floored at zero, so a unit at or
        under a pound adds nothing — multiplied by 42 cents per pound, rounded half up to
        whole cents."

        Design: Difficulty/combinatorial_formula/mcf_volume_discount_tier_keyed_on_pre_discount_total
        """
        ctx = setup_baseline()
        bigger = place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 40, 2.00, "ZONE_2",
            "SELF_FULFILLED", 19400,
        )
        smaller = place_multi_channel_order(
            ctx["seller_id"], ctx["listing_id"], 39, 2.00, "ZONE_2",
            "SELF_FULFILLED", 19400,
        )
        assert smaller["mcf_fee_cents"] == 19500
        assert smaller["mcf_fee_cents"] > bigger["mcf_fee_cents"]
        assert smaller["fee_advantage_cents"] == -100
        assert smaller["recommended_channel"] == "SELF_FULFILLED"
        assert smaller["order_status"] == "SELF_SHIPPED"
        assert read_seller(ctx["seller_id"])["mcf_fee_accrued_cents"] == 0
