"""Declared formulas: clamps, cumulative recognition, marginal tiers, bands, ratings and buckets."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    assertions,
    factories,
    fixtures,
    make_partner_account_lead_headers,
)

AMENDED_TIERS = [
    {"through_cents": 100000, "partner_rate": 0.60},
    {"through_cents": 200000, "partner_rate": 0.50},
    {"through_cents": None, "partner_rate": 0.40},
]


class TestDemandScoreClamps:
    def test_every_component_ceiling_binds_and_the_modality_factor_scales_once(self, api):
        """A saturated proposal scores 75 raw, then 69.00 after the single SYNCHRONOUS factor.

        PRD: "Four weighted components are summed and then scaled once by a modality factor. The
        enrollment component takes the effective projection divided by a projection ceiling of 400
        annual enrollments, capped at 1, and multiplies it by a weight of 40. The competition
        component takes 1 less the `competitor_program_count` divided by a competitor ceiling of
        30, floored at 0 so a hyper-competitive discipline contributes nothing rather than a
        negative amount, and multiplies it by a weight of 25. The wage component takes
        `regional_wage_premium_pct` divided by a wage-premium ceiling of 20 percentage points,
        capped at 1, and multiplies it by a weight of 20. The employer component takes
        `employer_partner_count` divided by an employer ceiling of 15, capped at 1, and multiplies
        it by a weight of 15."
        PRD: "Those four component values are added to a raw score, and the raw score is
        multiplied by the modality factor — 1.00 for `ASYNCHRONOUS`, 0.92 for `SYNCHRONOUS`, 0.96
        for `HYBRID` — exactly once, on the summed raw score and never per component."

        Design: Corner/calculations/demand_score_clamps_every_component_and_applies_the_modality_factor_once
        """
        fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
        partnership = fixtures.create_executed_partnership(api)
        ps_id = partnership["id"]

        response = api.create_program(
            factories.program_payload(
                ps_id,
                program_name="MEd Online",
                cip_code="13.0401",
                delivery_modality="SYNCHRONOUS",
                credits_to_complete=30,
                projected_annual_enrollments=900,
                competitor_program_count=40,
                regional_wage_premium_pct=60.0,
                employer_partner_count=20,
                prior_year_inquiry_volume=6000,
            ),
            headers=make_partner_account_lead_headers(ps_id),
        )
        program = validate_success(response, 201)

        assertions.assert_score_2dp(program["demand_score_screening"], "demand_score_screening")
        assert program["demand_score_screening"] == pytest.approx(69.00, abs=0.005)
        assert program["demand_score_confirmed"] == pytest.approx(69.00, abs=0.005)
        assert program["status"] == "DRAFT"


class TestRecognitionAcrossConsecutivePeriods:
    def test_the_second_period_line_is_the_cumulative_curve_minus_the_first(self, api):
        """October recognises cum(10-31) less cum(09-30), so the two lines never drift.

        PRD: "The cumulative recognised amount as of a date is `tuition_charged_cents` multiplied
        by that elapsed count, divided by the term length, rounded half up to whole cents. The
        line's amount is then the cumulative amount as of `period_end` minus the cumulative amount
        as of the day immediately before `period_start`. This cumulative-minus-prior form is
        mandatory: computing a period slice directly would let successive periods drift away from
        the cumulative curve."
        PRD: "Step 4 sets `marketing_recoupment_cents` to the smaller of the partnership's
        `unrecouped_marketing_spend_cents` and that ceiling."

        Design: Corner/calculations/recognition_lines_follow_the_cumulative_curve_across_two_consecutive_periods
        """
        context = fixtures.build_september_statement(
            api, credits_completed=None, marketing_spend_cents=300000
        )
        september = context["statement"]
        assert september["recognized_revenue_cents"] == 159198
        assert september["net_payable_cents"] == 73919

        fixtures.set_clock(api, fixtures.CLOCK_NOV_1)
        october = fixtures.cut_statement(
            api, context["ps_id"], period_start="2026-10-01", period_end="2026-10-31"
        )

        assert october["line_count"] == 1
        assert october["recognized_revenue_cents"] == 164505
        assert october["share_gross_cents"] == 94590
        assert october["marketing_recoupment_cents"] == 14188
        assert october["subtotal_cents"] == 80402
        assert october["holdback_cents"] == 4020
        assert october["net_payable_cents"] == 76382

        partnership = fixtures.read_partnership(api, context["ps_id"])
        assert partnership["contract_year_recognized_cents"] == 323703


class TestAmendedTiersAreMarginal:
    def test_a_line_straddling_the_first_boundary_is_paid_at_marginal_rates(self, api):
        """100,000 at 0.60 plus 59,198 at 0.50, not the whole line at the opening rate.

        PRD: "A tier's room is its `through_cents` minus the running position, except that the
        final unbounded tier — the one whose `through_cents` is null — always has room for
        whatever remains. A tier whose room is zero or negative is already exhausted and is
        skipped. Otherwise the amount taken from that tier is the smaller of the remaining line
        amount and the tier's room; the taken amount multiplied by that tier's `partner_rate` is
        added to the line's accumulator; the taken amount is subtracted from the remaining line
        amount and added to the running position; and the walk stops for this line once nothing
        remains."
        PRD: "Beyond the mandatory `expected_partnership_version` of §2.6, the amendment may carry
        any of `term_months`, `revenue_share_tiers`, `marketing_budget_cents`, `refund_schedule`,
        `revenue_recognition_method` and `fee_schedule_monthly_cents`."

        Design: Corner/calculations/amended_revenue_share_tiers_apply_marginal_rates_across_a_straddled_boundary
        """
        context = fixtures.build_paid_enrollment(
            api, marketing_spend_cents=300000, final_clock=fixtures.CLOCK_OCT_1
        )
        ps_id = context["ps_id"]

        amended = validate_success(
            api.amend_partnership_terms(
                ps_id,
                {
                    "expected_partnership_version": fixtures.current_partnership_version(api, ps_id),
                    "revenue_share_tiers": AMENDED_TIERS,
                },
                headers=make_partner_account_lead_headers(ps_id),
            ),
            200,
        )
        assert amended["revenue_share_tiers"] == AMENDED_TIERS

        statement = fixtures.cut_statement(api, ps_id)

        assert statement["recognized_revenue_cents"] == 159198
        assert statement["share_gross_cents"] == 89599
        assert statement["marketing_recoupment_cents"] == 13439
        assert statement["subtotal_cents"] == 76160
        assert statement["holdback_pct"] == pytest.approx(0.05, abs=0.0001)
        assert statement["holdback_cents"] == 3808
        assert statement["net_payable_cents"] == 72352


class TestRefundBandSelection:
    def test_day_seven_keeps_the_full_band_while_day_eight_falls_to_the_half_band(self, api):
        """Two identical enrollments one calendar day apart land in different bands.

        PRD: "Next, `refund_pct_applied` is the `refund_pct` of the **first** band of
        `refund_schedule`, in the schedule's declared order, whose `through_day` is either null or
        greater than or equal to `days_elapsed_at_withdrawal`."
        PRD: "The comparison is inclusive on `through_day`, which is why under the standard
        schedule a day-7 withdrawal takes the full-refund band while a day-8 withdrawal takes the
        half band."

        Design: Corner/calculations/refund_band_selection_is_inclusive_on_through_day
        """
        context = fixtures.build_paid_enrollment(api)
        fixtures.add_second_enrollment(api, context)
        fixtures.post_tuition_entry(api, context["en2_id"])
        fixtures.set_clock(api, fixtures.CLOCK_SEP_8)

        first = fixtures.withdraw_enrollment(
            api, context["en_id"], "2026-09-07", withdrawal_reason="Relocated"
        )
        second = fixtures.withdraw_enrollment(
            api,
            context["en2_id"],
            "2026-09-08",
            withdrawal_reason="Employer sponsorship withdrawn",
        )

        assert first["days_elapsed_at_withdrawal"] == 7
        assert first["refund_pct_applied"] == pytest.approx(1.00, abs=0.0001)
        assert first["refunded_cents"] == 562500

        assert second["days_elapsed_at_withdrawal"] == 8
        assert second["refund_pct_applied"] == pytest.approx(0.50, abs=0.0001)
        assert second["refunded_cents"] == 281250

        partnership = fixtures.read_partnership(api, context["ps_id"])
        assert partnership["collected_tuition_cents"] == 281250
        assert fixtures.read_counselor(api, context["co_id"])["clawback_pending_cents"] == 150000


class TestThinPipelineIsCountedButNotRated:
    def test_three_rated_leads_leave_the_counselor_unrated(self, api):
        """The run includes the counselor yet declines to rate a pipeline below four leads.

        PRD: "When `rated_lead_count` is fewer than 4, there is too little signal to judge:
        `conversion_rate` is set to 0.0000 and `performance_status` is set to `NOT_RATED`."
        PRD: "A run reports back an `evaluated_count` of the counselors it included, a
        `rated_count` of those that had at least 4 rated leads and therefore received a real
        rating, a `downgraded_count` of those whose breach ratio applied the one-step downgrade,
        and a `run_completed_at` stamped from the logical clock."

        Design: Corner/calculations/performance_run_leaves_a_thin_pipeline_not_rated
        """
        context = fixtures.build_launched_program(
            api, service_domains=("MARKETING", "ENROLLMENT_COUNSELING")
        )
        ps_id, pg_id, co_id = context["ps_id"], context["pg_id"], context["co_id"]

        first = fixtures.create_applied_lead(api, ps_id, pg_id, co_id)
        fixtures.enroll_lead(api, first["id"])
        second = fixtures.create_lead(
            api, ps_id, pg_id, co_id, prospect_external_id="P-1002", source_channel="PAID_SOCIAL"
        )
        fixtures.contact_lead(api, ps_id, second["id"], 9)
        third = fixtures.create_lead(
            api, ps_id, pg_id, co_id, prospect_external_id="P-1003", source_channel="ORGANIC"
        )
        fixtures.contact_lead(api, ps_id, third["id"], 40)

        run = fixtures.run_performance_evaluation(api, ps_id)

        assert run["evaluated_count"] == 1
        assert run["rated_count"] == 0
        assert run["downgraded_count"] == 0
        assertions.assert_logical_instant(run["run_completed_at"], fixtures.CLOCK_AUG_1)

        counselor = fixtures.read_counselor(api, co_id)
        assert counselor["rated_lead_count"] == 3
        assert counselor["enrolled_lead_count"] == 1
        assert counselor["sla_breach_count"] == 1
        assert counselor["conversion_rate"] == pytest.approx(0.0, abs=0.0001)
        assert counselor["performance_status"] == "NOT_RATED"


class TestTeachOutLiabilityBuckets:
    def test_the_three_buckets_conserve_the_cost_with_a_floored_partner_cap(self, api):
        """An empty holdback pool, a floor-capped partner share and the residual absorbing the rest.

        PRD: "`affected_enrollment_count` is the number of the program's enrollments in `ENROLLED`
        or `ACTIVE` at plan creation, `remaining_credit_count` is the sum over those affected
        enrollments of `credits_enrolled` less `credits_completed`, and `teach_out_cost_cents` is
        that remaining credit count multiplied by a teach-out unit cost of $180 per credit."
        PRD: "What remains after the holdback pool is the cost minus `holdback_applied_cents`.
        `partner_obligation_cents` is the smaller of that remainder and a cap of
        `teach_out_cost_cents` multiplied by 0.40 taken with a **floor**, not rounded half up: the
        partner's cash exposure is capped at forty percent of the total teach-out cost no matter
        how large the residual is."
        PRD: "Otherwise it is the sum of `design_cost_cents` over the program's courses whose
        `design_status` is `APPROVED`, `DESIGN_SUSPENDED` or `RETIRED`, multiplied by the scope
        factor and rounded half up to whole cents — half the book value for
        `COURSE_CONTENT_ONLY`, three quarters for `COURSE_CONTENT_AND_LEAD_DATA`, and the whole of
        it for `FULL_PLATFORM`."

        Design: Corner/calculations/teach_out_liability_buckets_sum_exactly_to_the_teach_out_cost
        """
        context = fixtures.build_paid_enrollment(api, credits_completed=3)
        assert fixtures.read_partnership(api, context["ps_id"])["holdback_balance_cents"] == 0

        fixtures.begin_teach_out(
            api,
            context["pg_id"],
            teach_out_reason="Program discontinued after portfolio review",
        )
        plan = fixtures.draft_teach_out_plan(
            api,
            context["pg_id"],
            teach_out_end_date="2027-01-15",
            student_notification_date="2026-09-05",
            asset_transfer_scope="COURSE_CONTENT_ONLY",
            partner_obligation_note="Partner funds capped share of teach-out delivery.",
        )
        certified = fixtures.certify_teach_out_plan(
            api,
            plan["id"],
            certification_note="Notice period and asset inventory verified.",
        )

        assert certified["status"] == "CERTIFIED"
        assert certified["affected_enrollment_count"] == 1
        assert certified["remaining_credit_count"] == 6
        assert certified["teach_out_cost_cents"] == 108000
        assert certified["holdback_applied_cents"] == 0
        assert certified["partner_obligation_cents"] == 43200
        assert certified["university_residual_cents"] == 64800
        assert certified["transferred_asset_value_cents"] == 750000
        assert certified["certified_by_user_id"] == "auditor-1"
        assertions.assert_teach_out_buckets_conserve(certified)
