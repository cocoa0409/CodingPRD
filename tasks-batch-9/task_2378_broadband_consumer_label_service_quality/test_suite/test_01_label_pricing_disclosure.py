"""Pricing disclosure on a drafted consumer label.

Drafting a label computes the whole priced face of the disclosure: the fee
itemisation with its per-line rounding, the low-income discount benefit derived
from the gross phase totals, and the two first-year figures the label prints
side by side. These tests exercise those calculations through
`POST /label-versions`, the operation that produces them, and read the figures
straight off the created draft.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers.assertions import itemization_amount
from test_helpers.constants import DISCOUNT_MONTHLY_CAP_CENTS, REFERENCE_NOW
from test_helpers.factories import (
    build_fixed_fee_payload,
    build_label_version_payload,
    build_percentage_fee_payload,
)
from test_helpers.fixtures import (
    add_fee_line,
    create_reference_plan,
    create_service_plan,
    current_plan_version,
    set_clock,
)
from test_helpers.test_users import COMPLIANCE_OFFICER_HEADERS
from test_helpers.types import (
    EtfProrationPolicy,
    FeeLabelCategory,
    ItemizationPhase,
    Technology,
)


# ---------------------------------------------------------------------------
# Local setup chains
# ---------------------------------------------------------------------------


def _draft_label_response(plan_id: str, effective_from: str = REFERENCE_NOW):
    """The operation under test: draft a label for `plan_id`.

    Returns the raw response so the test validates the create itself rather
    than a later read.
    """
    payload = build_label_version_payload(
        plan_id, effective_from, current_plan_version(plan_id)
    )
    return api_client.create_label_version(payload, COMPLIANCE_OFFICER_HEADERS)


def _plan_with_two_percentage_lines() -> Dict[str, Any]:
    """A plan carrying one fixed monthly line and the two percentage lines
    whose exact cent amounts both have fractional parts below a half.

    The introductory base charge of 4999 cents makes the 3.25% line 162.4675
    exact cents and the 2.11% line 105.4789 exact cents, so the two fractional
    remainders together exceed a half and the rounding order is observable.
    """
    plan = create_service_plan()
    add_fee_line(
        plan["id"],
        build_fixed_fee_payload("EQUIP_RENTAL", 1500, description="Equipment rental"),
    )
    add_fee_line(
        plan["id"],
        build_percentage_fee_payload(
            "REG_RECOVERY",
            0.0325,
            description="Regulatory cost recovery",
            is_regulatory_recovery=True,
        ),
    )
    add_fee_line(
        plan["id"],
        build_percentage_fee_payload(
            "STATE_USF",
            0.0211,
            label_category=FeeLabelCategory.GOVERNMENT_TAX.value,
            description="State universal service fund",
        ),
    )
    return plan


def _cheap_plan_below_the_discount_cap() -> Dict[str, Any]:
    """A plan whose gross introductory total sits below the monthly discount
    cap, so the benefit is clamped by the bill rather than by the cap."""
    plan = create_service_plan(
        display_name="Lifeline 9",
        technology=Technology.DSL.value,
        advertised_download_mbps=25,
        advertised_upload_mbps=3,
        monthly_price_cents=1000,
        early_termination_fee_cents=0,
        intro_price_cents=1000,
        intro_term_months=3,
        data_allowance_gb=None,
        overage_rate_cents_per_gb=0,
        etf_proration_policy=EtfProrationPolicy.NONE.value,
        discount_program_eligible=True,
    )
    add_fee_line(
        plan["id"],
        build_fixed_fee_payload("LINE_FEE", 500, description="Copper line fee"),
    )
    return plan


# ---------------------------------------------------------------------------
# The two first-year disclosure variants
# ---------------------------------------------------------------------------


class TestFirstYearDisclosureVariants:
    """Both first-year figures are computed from the one fee itemisation of a
    single label row."""

    def test_first_year_variants_diverge_on_the_same_label(self):
        """The promotion-weighted and annualised figures read the same fees.

        PRD: "Under the promotion-weighted variant, `first_year_total_promo_weighted_cents`
        is `one_time_fee_total_cents` plus `net_monthly_intro_cents` multiplied by that
        number of introductory months, plus `net_monthly_post_promo_cents` multiplied by
        the remaining months of the twelve-month disclosure year."

        Design: Difficulty/dual_variant_calc/first_year_disclosure_variants_diverge_on_same_label
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()

        label = validate_success(
            _draft_label_response(plan["id"]), expected_status=201
        )

        assert label["one_time_fee_total_cents"] == 9900, (
            "the one-time block is the sum of the plan's ONE_TIME fee lines: "
            f"expected 9900, got {label['one_time_fee_total_cents']}"
        )
        assert label["net_monthly_intro_cents"] == 3766, (
            "introductory net monthly charge: expected 3766, "
            f"got {label['net_monthly_intro_cents']}"
        )
        assert label["net_monthly_post_promo_cents"] == 7628, (
            "post-promotional net monthly charge: expected 7628, "
            f"got {label['net_monthly_post_promo_cents']}"
        )
        assert label["first_year_total_promo_weighted_cents"] == 78264, (
            "promotion-weighted first-year total: expected 78264, "
            f"got {label['first_year_total_promo_weighted_cents']}"
        )
        assert label["first_year_total_post_promo_cents"] == 101436, (
            "post-promotional annualised first-year total: expected 101436, "
            f"got {label['first_year_total_post_promo_cents']}"
        )

    def test_annualised_first_year_total_exceeds_the_promotion_weighted_one(self):
        """The annualised variant ignores the promotion and so prints higher.

        PRD: "Whenever the post-promotional net exceeds the introductory net and at
        least one introductory month is billed, the annualised figure is strictly the
        larger of the two."

        Design: Difficulty/dual_variant_calc/first_year_disclosure_variants_diverge_on_same_label
        """
        set_clock(REFERENCE_NOW)
        plan = create_reference_plan()

        label = validate_success(
            _draft_label_response(plan["id"]), expected_status=201
        )

        assert (
            label["net_monthly_post_promo_cents"] > label["net_monthly_intro_cents"]
        ), "the premise of the comparison is that the post-promotional net is higher"
        assert (
            label["first_year_total_post_promo_cents"]
            > label["first_year_total_promo_weighted_cents"]
        ), "the annualised figure must be strictly the larger of the two"
        divergence = (
            label["first_year_total_post_promo_cents"]
            - label["first_year_total_promo_weighted_cents"]
        )
        assert divergence == 23172, (
            "the two variants must diverge by exactly 23172 cents on this label, "
            f"got {divergence}"
        )


# ---------------------------------------------------------------------------
# Rounding order on the percentage fee lines
# ---------------------------------------------------------------------------


class TestPercentageFeeRoundingOrder:
    """Each percentage line is rounded to whole cents before it is summed into
    the phase total."""

    def test_intro_percentage_lines_are_rounded_before_they_are_summed(self):
        """Rounding each line first gives 6766, not the sum-then-round 6767.

        PRD: "Accumulating fractional cents across several percentage lines and rounding
        the phase total once is explicitly the wrong algorithm and yields a total that
        differs by a cent."

        Design: Difficulty/combinatorial_formula/percentage_fee_rounding_order_pinned_round_then_sum
        """
        set_clock(REFERENCE_NOW)
        plan = _plan_with_two_percentage_lines()

        label = validate_success(
            _draft_label_response(plan["id"]), expected_status=201
        )

        reg_recovery = itemization_amount(
            label, "REG_RECOVERY", ItemizationPhase.INTRO.value
        )
        state_usf = itemization_amount(
            label, "STATE_USF", ItemizationPhase.INTRO.value
        )
        assert reg_recovery == 162, (
            "the 3.25% line on the 4999-cent introductory base is 162.4675 exact "
            f"cents and must be itemised as 162, got {reg_recovery}"
        )
        assert state_usf == 105, (
            "the 2.11% line on the 4999-cent introductory base is 105.4789 exact "
            f"cents and must be itemised as 105, got {state_usf}"
        )
        assert label["monthly_total_intro_cents"] == 6766, (
            "gross introductory monthly total: expected 6766, "
            f"got {label['monthly_total_intro_cents']}"
        )
        assert label["monthly_total_intro_cents"] != 6767, (
            "6767 is the forbidden result of summing the exact fractions and "
            "rounding the phase total once"
        )

    def test_post_promotional_percentage_lines_are_rounded_line_by_line(self):
        """The post-promotional phase total is the base plus already-rounded lines.

        PRD: "When a percentage-based fee line is itemised, the product of its rate and
        the phase's base charge is rounded to a whole number of cents *before* it is
        added to anything else, and the phase total is the sum of those already-rounded
        amounts plus the base charge."

        Design: Difficulty/combinatorial_formula/percentage_fee_rounding_order_pinned_round_then_sum
        """
        set_clock(REFERENCE_NOW)
        plan = _plan_with_two_percentage_lines()

        label = validate_success(
            _draft_label_response(plan["id"]), expected_status=201
        )

        reg_recovery = itemization_amount(
            label, "REG_RECOVERY", ItemizationPhase.POST_PROMO.value
        )
        state_usf = itemization_amount(
            label, "STATE_USF", ItemizationPhase.POST_PROMO.value
        )
        assert reg_recovery == 260, (
            "the 3.25% line on the 7999-cent post-promotional base must be itemised "
            f"as 260, got {reg_recovery}"
        )
        assert state_usf == 169, (
            "the 2.11% line on the 7999-cent post-promotional base must be itemised "
            f"as 169, got {state_usf}"
        )

        itemised = sum(
            entry["amount_cents"]
            for entry in label["fee_itemization"]
            if entry["phase"] == ItemizationPhase.POST_PROMO.value
        )
        expected_total = plan["monthly_price_cents"] + itemised
        assert label["monthly_total_post_promo_cents"] == expected_total, (
            "the phase total must equal the base charge plus the sum of the "
            f"already-rounded line amounts ({expected_total}), got "
            f"{label['monthly_total_post_promo_cents']}"
        )


# ---------------------------------------------------------------------------
# Evaluation order of the discount benefit against the percentage lines
# ---------------------------------------------------------------------------


class TestDiscountBenefitEvaluationOrder:
    """The benefit is derived from the gross phase total, and the percentage
    lines are never recomputed against the net."""

    def test_benefit_is_derived_from_the_gross_total_not_from_a_discounted_base(self):
        """Gross first, then benefit, then net — never benefit before the fees.

        PRD: "Percentage lines are never recomputed against the net amount, and the
        benefit is never subtracted from the base before the percentage lines are
        computed."

        Design: Difficulty/combinatorial_formula/discount_benefit_evaluation_order_after_percentage_fees
        """
        set_clock(REFERENCE_NOW)
        plan = _plan_with_two_percentage_lines()

        label = validate_success(
            _draft_label_response(plan["id"]), expected_status=201
        )

        assert label["monthly_total_intro_cents"] == 6766, (
            "the gross introductory total is computed against the gross base: "
            f"expected 6766, got {label['monthly_total_intro_cents']}"
        )
        assert label["discount_program_benefit_intro_cents"] == (
            DISCOUNT_MONTHLY_CAP_CENTS
        ), (
            "the introductory benefit is capped at the monthly cap: expected "
            f"{DISCOUNT_MONTHLY_CAP_CENTS}, got "
            f"{label['discount_program_benefit_intro_cents']}"
        )
        assert label["net_monthly_intro_cents"] == 3766, (
            "introductory net monthly charge: expected 3766, "
            f"got {label['net_monthly_intro_cents']}"
        )
        assert label["net_monthly_intro_cents"] != 3687, (
            "3687 is the forbidden result of deducting the benefit from the base "
            "before the percentage lines are computed"
        )

        assert label["discount_program_benefit_post_promo_cents"] == (
            DISCOUNT_MONTHLY_CAP_CENTS
        ), (
            "the post-promotional benefit is capped at the monthly cap: expected "
            f"{DISCOUNT_MONTHLY_CAP_CENTS}, got "
            f"{label['discount_program_benefit_post_promo_cents']}"
        )
        assert label["net_monthly_post_promo_cents"] == (
            label["monthly_total_post_promo_cents"]
            - label["discount_program_benefit_post_promo_cents"]
        ), "the post-promotional net must be the gross total minus the benefit"

    def test_discount_benefit_clamps_at_the_gross_monthly_bill(self):
        """A bill below the cap clamps the benefit and drives the net to zero.

        PRD: "When it is true, each phase's benefit is the lesser of 3,000 cents — a
        thirty-dollar monthly cap — and that phase's gross monthly total, so the benefit
        clamps at the bill and the net can reach exactly zero but never goes negative."

        Design: Difficulty/combinatorial_formula/discount_benefit_evaluation_order_after_percentage_fees
        """
        set_clock(REFERENCE_NOW)
        plan = _cheap_plan_below_the_discount_cap()

        label = validate_success(
            _draft_label_response(plan["id"]), expected_status=201
        )

        assert label["monthly_total_intro_cents"] == 1500, (
            "gross introductory monthly total: expected 1500, "
            f"got {label['monthly_total_intro_cents']}"
        )
        assert label["discount_program_benefit_intro_cents"] == 1500, (
            "the benefit clamps at the gross bill rather than at the cap: expected "
            f"1500, got {label['discount_program_benefit_intro_cents']}"
        )
        assert label["net_monthly_intro_cents"] == 0, (
            "the net reaches exactly zero and never goes negative: expected 0, "
            f"got {label['net_monthly_intro_cents']}"
        )
