"""Fee assessment: valuation vs square-foot method, marginal tiers, rounding order,
minimum-fee floor, immediate fee visibility, and VOID-payment exclusion.

PRD §3.2 (assessing the fee), §3.3 (paying / balance), §2.8 (rounding).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    create_jurisdiction,
    create_contractor,
    create_permit_payload,
    make_applicant_headers,
    pay_permit,
)


def _permit(api, jur_id, con_id, **overrides):
    resp = api.create_permit(
        create_permit_payload(jur_id, con_id, **overrides), make_applicant_headers())
    return validate_success(resp, 201)


class TestDualVariantFee:
    def test_valuation_method_assessed_and_total_fee(self, api):
        """PRD §3.2: "Under the valuation method the assessed valuation is the
        `declared_valuation` taken verbatim."
        PRD §3.2: "The `total_permit_fee` is the sum of the rounded base permit
        fee and the rounded plan-review surcharge, itself rounded to two decimal places."

        Design: Difficulty/dual_variant_calc/assessed_valuation_method_vs_square_foot_method
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="NEW_CONSTRUCTION", fee_method="VALUATION",
                         declared_valuation=600000)
        assert permit["assessed_valuation"] == 600000
        assert permit["total_permit_fee"] == 7755.00

    def test_square_foot_method_imputes_assessed_and_total_fee(self, api):
        """PRD §3.2: "Under the square-foot method the assessed valuation is
        instead imputed as the `floor_area_sqft` multiplied by the jurisdiction's
        `square_foot_rate`, and the `declared_valuation` is ignored entirely."

        Design: Difficulty/dual_variant_calc/assessed_valuation_method_vs_square_foot_method
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="ALTERATION", fee_method="SQUARE_FOOT",
                         floor_area_sqft=2000)
        assert permit["assessed_valuation"] == 240000
        assert permit["total_permit_fee"] == 3333.00


class TestMarginalTierBaseFee:
    def test_three_tier_marginal_base_fee_not_flat(self, api):
        """PRD §3.2: "The first $50,000 of assessed valuation forms the first tier
        and is charged at the full base rate. The portion of valuation above
        $50,000 and up to $500,000 — at most $450,000 of value — forms the second
        tier and is charged at 80 percent of the base rate. Any valuation above
        $500,000 forms the third tier and is charged at 60 percent of the base rate."

        Design: Difficulty/combinatorial_formula/base_permit_fee_three_tier_marginal_selection
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="NEW_CONSTRUCTION", fee_method="VALUATION",
                         declared_valuation=600000)
        assert permit["assessed_valuation"] == 600000
        assert permit["base_permit_fee"] == 4700.00

    def test_marginal_base_fee_not_equal_to_flat_rate(self, api):
        """PRD §3.2: "the system derives the `base_permit_fee` using a
        progressive, marginal-tier schedule — each band of valuation is charged
        at its own rate, rather than the whole valuation being charged at a single
        rate."

        Design: Difficulty/combinatorial_formula/base_permit_fee_three_tier_marginal_selection
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="NEW_CONSTRUCTION", fee_method="VALUATION",
                         declared_valuation=600000)
        # A flat rate would be 600000/1000*10 = 6000.00; the marginal schedule gives 4700.00.
        assert permit["base_permit_fee"] == 4700.00
        assert permit["base_permit_fee"] != 6000.00

    def test_tier1_ceiling_no_spillover_at_50000(self, api):
        """PRD §3.2: "The first $50,000 of assessed valuation forms the first tier
        and is charged at the full base rate."

        Design: Corner/calculations/tiered_fee_boundary_at_50000
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="ADDITION", fee_method="VALUATION",
                         declared_valuation=50000)
        assert permit["base_permit_fee"] == 500.00
        assert permit["total_permit_fee"] == 825.00


class TestRoundingOrder:
    def test_round_each_then_sum_pinned_order(self, api):
        """PRD §3.2: "This per-component rounding order is binding: round the base,
        round the surcharge of the rounded base, then sum — do not compute the
        total as a single rounding of the base scaled by one plus the percentage."

        Design: Difficulty/combinatorial_formula/total_permit_fee_rounding_order_round_each_then_sum
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="ADDITION", fee_method="VALUATION",
                         declared_valuation=53333)
        assert permit["base_permit_fee"] == 526.66
        assert permit["plan_review_fee"] == 342.33
        assert permit["total_permit_fee"] == 868.99

    def test_round_each_then_sum_distinct_from_sum_then_round(self, api):
        """PRD §3.2: "The `plan_review_fee` surcharge is then computed from the
        already-rounded base permit fee: it is the base permit fee multiplied by
        the jurisdiction's `plan_review_fee_pct`, rounded to two decimal places,
        round half up."

        Design: Difficulty/combinatorial_formula/total_permit_fee_rounding_order_round_each_then_sum
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="ADDITION", fee_method="VALUATION",
                         declared_valuation=53333)
        # round-each-then-sum gives 868.99, NOT round(526.664*1.65)=869.00.
        assert permit["total_permit_fee"] == 868.99
        assert permit["total_permit_fee"] != 869.00


class TestMinimumFeeFloor:
    def test_minimum_fee_floor_applied_after_rounding(self, api):
        """PRD §3.2: "the base permit fee is the greater of the rounded raw fee
        and the minimum, with the floor applied only after the rounding."

        Design: Corner/calculations/min_floor_base_fee_applied
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="REPAIR", fee_method="VALUATION",
                         declared_valuation=2000)
        assert permit["base_permit_fee"] == 100.00
        assert permit["total_permit_fee"] == 165.00


class TestImmediateFeeVisibility:
    def test_total_fee_present_in_create_response(self, api):
        """PRD §3.2: "The `total_permit_fee` is the sum of the rounded base permit
        fee and the rounded plan-review surcharge, itself rounded to two decimal places."

        Design: Corner/consistency_model/immediate_consistency_fee_visible_in_create_response
        """
        jur = create_jurisdiction()
        con = create_contractor()
        resp = api.create_permit(
            create_permit_payload(jur["id"], con["id"],
                                  work_class="NEW_CONSTRUCTION", fee_method="VALUATION",
                                  declared_valuation=600000),
            make_applicant_headers())
        data = validate_success(resp, 201)
        assert data["total_permit_fee"] == 7755.00


class TestVoidPaymentExclusion:
    def test_void_payment_excluded_from_amount_paid(self, api):
        """PRD §3.3: "The permit's `amount_paid` is the sum of the `amount` of
        every `FeePayment` for that permit whose `payment_status` is `CLEARED`;
        payments marked `VOID` are excluded from the total."

        Design: Corner/calculations/amount_paid_excludes_void_payment
        """
        jur = create_jurisdiction()
        con = create_contractor()
        permit = _permit(api, jur["id"], con["id"],
                         work_class="REPAIR", fee_method="VALUATION",
                         declared_valuation=2000)
        pay_permit(permit["id"], 100.00, payment_status="CLEARED")
        pay_permit(permit["id"], 65.00, payment_status="VOID")
        refreshed = validate_success(api.get_permit(permit["id"], make_applicant_headers()))
        assert refreshed["amount_paid"] == 100.00
        assert refreshed["balance_due"] == 65.00
