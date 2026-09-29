"""Two-variant money rules: cost allocation, risk scoring, invoice totalling, premium."""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE_CARL,
    OPS_ALICE,
    REVIEWER_BOB,
    approx_money,
    approx_weight,
    assert_order_dimensions,
    factories as f,
    find_by,
    fixtures as fx,
)

Json = Dict[str, Any]

# ---------------------------------------------------------------------------
# DDP short shipment: the provisional and final variants of the allocation
# ---------------------------------------------------------------------------

DDP_LINES = [
    {
        "line_no": 1,
        "quantity": 10.000,
        "unit_price_usd": 1000.0000,
        "net_weight_kg": 4500.000,
        "gross_weight_kg": 5000.000,
        "package_count": 10,
    },
    {
        "line_no": 2,
        "quantity": 10.000,
        "unit_price_usd": 500.0000,
        "net_weight_kg": 2700.000,
        "gross_weight_kg": 3000.000,
        "package_count": 6,
    },
]


def _ddp_short_shipment(api) -> Json:
    """A DDP order booked LCL on 8,000 kg and short shipped on its second line."""
    ctx = fx.cleared_order(
        api,
        order_overrides={
            "incoterm": "DDP",
            "incoterm_named_place": "DDP Busan",
            "destination_zone": "ZONE_2",
        },
        lines=DDP_LINES,
    )
    ctx = fx.booked_order(
        api,
        base=ctx,
        sailing_overrides={
            "destination_zone": "ZONE_2",
            "tariff_rate_per_1000kg_usd": 300.00,
            "capacity_weight_kg": 20000.000,
        },
        booking_overrides={"booked_weight_kg": 8000.000, "container_type": "LCL"},
    )
    ctx = fx.confirmed_booking(api, ctx)
    ctx = fx.shipped_order(api, ctx, shipped_quantities=[10.000, 4.000])
    return ctx


class TestProvisionalVersusFinalAllocation:
    def test_short_shipment_diverges_in_both_cost_variants(self, api):
        """PRD §3.6: "On a short shipment they diverge in five buckets at once
        — inland origin, main carriage, marine insurance, inland destination
        and import duty — and the divergence is **not** proportional to the
        shipped-value ratio, because export clearance and both terminal-handling
        charges are flat while main carriage and marine insurance carry floors."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_incoterm_cost_allocation_diverge_on_short_shipment
        """
        ctx = _ddp_short_shipment(api)
        order = ctx["order"]

        assert_order_dimensions(order, fulfillment="SHORT_SHIPPED")
        assert order["ordered_goods_value_usd"] == approx_money(15000.00)
        assert order["provisional_seller_cost_usd"] == approx_money(5381.00)
        assert order["provisional_buyer_cost_usd"] == approx_money(0.00)
        assert order["final_seller_cost_usd"] == approx_money(4744.00)
        assert order["final_buyer_cost_usd"] == approx_money(0.00)
        assert order["cost_allocation_variance_usd"] == approx_money(-637.00)

    def test_short_shipment_records_shipped_and_short_values_with_a_bill_of_lading(
        self, api
    ):
        """PRD §3.6: "the order moves from `BOOKED` to `SHORT_SHIPPED` and
        `short_shipped_value_usd` is set to `ordered_goods_value_usd` less
        `shipped_goods_value_usd`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_incoterm_cost_allocation_diverge_on_short_shipment
        """
        ctx = _ddp_short_shipment(api)
        order = ctx["order"]

        assert order["shipped_goods_value_usd"] == approx_money(12000.00)
        assert order["short_shipped_value_usd"] == approx_money(3000.00)
        assert ctx["bill_of_lading"]["doc_type"] == "BILL_OF_LADING"
        assert ctx["bill_of_lading"]["status"] == "ISSUED"
        assert ctx["booking"]["status"] == "SHIPPED"

        lines = fx.rows(api.list_order_shipment_lines(ctx["order_id"], OPS_ALICE))
        assert find_by(lines, line_no=1)["shipped_quantity"] == approx_weight(10.000)
        assert find_by(lines, line_no=2)["shipped_quantity"] == approx_weight(4.000)


# ---------------------------------------------------------------------------
# The same finding set scored by the terms variant and the examination variant
# ---------------------------------------------------------------------------

FOB_ZONE_1_LINE = [
    {
        "line_no": 1,
        "quantity": 100.000,
        "unit_price_usd": 250.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 20,
    }
]


def _two_variant_scoring(api) -> Json:
    """One MINOR terms finding accepted, then one MAJOR discrepancy on the tender."""
    ctx = fx.cleared_order(
        api,
        order_overrides={"destination_zone": "ZONE_1", "incoterm_named_place": "FOB Busan"},
        lines=FOB_ZONE_1_LINE,
    )
    ctx = fx.booked_order(
        api,
        base=ctx,
        sailing_overrides={"destination_zone": "ZONE_1"},
    )
    ctx = fx.confirmed_booking(api, ctx)
    ctx = fx.shipped_order(api, ctx)
    ctx = fx.captured_credit(
        api,
        ctx,
        lc_number="LC-2195-001",
        amount_usd=26000.00,
        tolerance_pct=5.00,
        availability="SIGHT",
        usance_days=0,
        expiry_date="2026-10-15T00:00:00Z",
        required_document_types=["COMMERCIAL_INVOICE", "BILL_OF_LADING"],
    )
    ctx = fx.opened_terms_review(api, ctx)
    ctx["terms_finding"] = fx.data(
        api.raise_terms_finding(
            ctx["review_id"],
            f.terms_finding_payload(
                code="DESCRIPTION_MISMATCH",
                severity="MINOR",
                clause_ref="DOCUMENTS",
                detail="goods description abbreviated against the credit wording",
            ),
            REVIEWER_BOB,
        )
    )
    ctx["review"] = fx.data(
        api.submit_terms_review(
            ctx["review_id"], {"recommendation": "ACCEPT"}, REVIEWER_BOB
        )
    )
    ctx = fx.lodged_presentation(api, ctx)
    return ctx


class TestTermsVersusExaminationScoring:
    def test_terms_variant_scores_the_minor_finding_at_full_weight(self, api):
        """PRD §3.4: "the carryover factor is always 1.0, because a terms review
        has no round concept; and `MINOR` findings always count."

        Design: Difficulty/dual_variant_calc/terms_review_vs_examination_risk_score_diverge_on_identical_finding_set
        """
        ctx = _two_variant_scoring(api)

        assert ctx["review"]["status"] == "SUBMITTED"
        assert ctx["review"]["recommendation"] == "ACCEPT"
        assert ctx["review"]["terms_risk_score"] == approx_money(5.00)
        assert ctx["review"]["finding_count"] == 1
        assert ctx["credit"]["max_drawable_usd"] == approx_money(27300.00)
        assert ctx["credit"]["min_drawable_usd"] == approx_money(24700.00)

    def test_examination_variant_adds_a_half_weight_carryover_of_the_terms_finding(
        self, api
    ):
        """PRD §3.7: "Its carryover factor is 1.0 for a finding whose
        `raised_in_round` equals the presentation's current `presentation_round`,
        and **0.5** for one raised in an earlier round — a stale discrepancy
        weighs half as much."

        Design: Difficulty/dual_variant_calc/terms_review_vs_examination_risk_score_diverge_on_identical_finding_set
        """
        ctx = _two_variant_scoring(api)
        presentation = fx.data(
            api.examine_presentation(
                ctx["presentation_id"],
                {
                    "findings": [
                        f.examination_finding(
                            code="AMOUNT_MISMATCH",
                            severity="MAJOR",
                            clause_ref="AMOUNT",
                            detail="invoice total disagrees with the credit amount",
                        )
                    ]
                },
                REVIEWER_BOB,
            )
        )

        assert presentation["status"] == "DISCREPANT"
        assert presentation["examination_risk_score"] == approx_money(25.00)
        assert presentation["open_finding_count"] == 1

        terms_finding = fx.data(api.get_finding(ctx["terms_finding"]["id"], REVIEWER_BOB))
        assert terms_finding["cure_status"] == "OPEN"
        assert terms_finding["raised_in_round"] == 0
        assert_order_dimensions(
            fx.read_order(api, ctx["order_id"]), settlement="LC_ACCEPTED"
        )


# ---------------------------------------------------------------------------
# Per-line rounding, then a pro-rata freight spread, then one FX multiplication
# ---------------------------------------------------------------------------

THREE_EQUAL_LINES = [
    {
        "line_no": n,
        "quantity": 3.000,
        "unit_price_usd": 10.0050,
        "net_weight_kg": 450.000,
        "gross_weight_kg": 500.000,
        "package_count": 5,
    }
    for n in (1, 2, 3)
]


def _cfr_eur_invoice(api) -> Json:
    """A CFR order invoiced in EUR whose freight pool splits three equal ways."""
    ctx = fx.cleared_order(
        api,
        order_overrides={
            "incoterm": "CFR",
            "incoterm_named_place": "CFR Busan",
            "destination_zone": "ZONE_1",
            "invoice_currency": "EUR",
            "fx_rate_usd_to_invoice": 0.912345,
        },
        lines=THREE_EQUAL_LINES,
    )
    ctx = fx.booked_order(
        api,
        base=ctx,
        sailing_overrides={
            "destination_zone": "ZONE_1",
            "tariff_rate_per_1000kg_usd": 500.00,
        },
        booking_overrides={"booked_weight_kg": 1500.000, "container_type": "LCL"},
    )
    ctx["invoice"] = fx.data(
        api.generate_document(
            f.document_payload(ctx["order_id"], "COMMERCIAL_INVOICE"), OPS_ALICE
        )
    )
    return ctx


class TestInvoiceTotallingChain:
    def test_freight_residual_lands_on_the_smaller_line_no_of_a_tie(self, api):
        """PRD §3.5: "it is added to exactly **one** line: the line with the
        **greatest** `line_net_usd`, with ties broken by the **smaller**
        `line_no`. The residual is never split, never distributed, and the sink
        is never chosen by `id`."

        Design: Difficulty/combinatorial_formula/per_line_round_then_prorata_freight_residual_to_line_1_then_single_fx
        """
        ctx = _cfr_eur_invoice(api)
        lines = fx.rows(api.list_order_shipment_lines(ctx["order_id"], OPS_ALICE))

        for line in lines:
            assert line["line_extended_usd"] == approx_money(30.02)
        assert ctx["order"]["ordered_goods_value_usd"] == approx_money(90.06)

        assert find_by(lines, line_no=1)["apportioned_freight_usd"] == approx_money(333.34)
        assert find_by(lines, line_no=2)["apportioned_freight_usd"] == approx_money(333.33)
        assert find_by(lines, line_no=3)["apportioned_freight_usd"] == approx_money(333.33)
        assert sum(line["apportioned_freight_usd"] for line in lines) == approx_money(
            1000.00
        )

    def test_usd_total_is_assembled_unrounded_then_converted_once(self, api):
        """PRD §2.9: "The USD invoice total is assembled from already-rounded USD
        components without any further USD rounding, and the FX multiplication is
        the single rounding applied to a total."

        Design: Difficulty/combinatorial_formula/per_line_round_then_prorata_freight_residual_to_line_1_then_single_fx
        """
        ctx = _cfr_eur_invoice(api)
        invoice = ctx["invoice"]

        assert invoice["status"] == "DRAFT"
        assert invoice["revision"] == 1
        assert invoice["declared_total_usd"] == approx_money(1090.06)
        assert invoice["declared_total_invoice_currency"] == approx_money(994.51)
        assert ctx["order"]["provisional_seller_cost_usd"] == approx_money(1584.00)
        assert ctx["order"]["provisional_buyer_cost_usd"] == approx_money(485.85)


# ---------------------------------------------------------------------------
# A premium tier keyed on the exposure this very policy will feed
# ---------------------------------------------------------------------------

BIG_LINE = [
    {
        "line_no": 1,
        "quantity": 120.000,
        "unit_price_usd": 1000.0000,
        "net_weight_kg": 1000.000,
        "gross_weight_kg": 1200.000,
        "package_count": 24,
    }
]


def _two_policy_ladder(api) -> Json:
    """POL-A priced, then charged by a credit acceptance, then POL-B priced."""
    buyer = fx.create_buyer(api, legal_name="Hanwha Trading Co", credit_rating="BBB")
    policy_a = fx.create_policy(
        api,
        buyer["id"],
        policy_number="POL-A",
        credit_limit_usd=200000.00,
        insured_pct=90.00,
        deductible_usd=5000.00,
    )
    ctx = fx.cleared_order_for_buyer(api, buyer, BIG_LINE)
    ctx = fx.accepted_credit(api, ctx, amount_usd=120000.00)
    ctx["policy_a"] = fx.read_policy(api, policy_a["id"])
    ctx["policy_b"] = fx.create_policy(
        api,
        buyer["id"],
        policy_number="POL-B",
        credit_limit_usd=150000.00,
        insured_pct=80.00,
        deductible_usd=10000.00,
    )
    return ctx


class TestPremiumTierBasis:
    def test_first_policy_prices_in_tier_one_with_the_fee_waived(self, api):
        """PRD §3.8: "It is exactly 0.00 when `exposure_tier` is `TIER_1` **and**
        `deductible_usd` is at least 5,000.00 USD."

        Design: Difficulty/combinatorial_formula/premium_tier_keyed_on_exposure_that_this_policy_will_itself_feed
        """
        ctx = _two_policy_ladder(api)

        assert ctx["policy_a"]["exposure_tier"] == "TIER_1"
        assert ctx["policy_a"]["premium_usd"] == approx_money(1530.00)
        assert ctx["policy_a"]["utilized_usd"] == approx_money(120000.00)
        assert ctx["policy_a"]["available_limit_usd"] == approx_money(80000.00)

    def test_second_policy_tier_basis_includes_the_exposure_the_first_now_carries(
        self, api
    ):
        """PRD §3.8: "a buyer's second policy can land in a higher tier than the
        first purely because the first policy's limit is inside the basis, and no
        later event ever re-prices either."

        Design: Difficulty/combinatorial_formula/premium_tier_keyed_on_exposure_that_this_policy_will_itself_feed
        """
        ctx = _two_policy_ladder(api)

        assert ctx["policy_b"]["exposure_tier"] == "TIER_2"
        assert ctx["policy_b"]["premium_usd"] == approx_money(1630.00)
        assert ctx["policy_b"]["utilized_usd"] == approx_money(0.00)

        buyer = fx.data(api.get_buyer(ctx["buyer_id"], COMPLIANCE_CARL))
        assert buyer["aggregate_exposure_usd"] == approx_money(120000.00)
