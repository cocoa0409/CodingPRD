"""Two computations in this service exist in two variants at once: the wage
figure (rounded early versus rounded late) and the credit figure (seat time
versus mastery). Both pairs are exercised on the same data so the divergence is
visible rather than incidental.
"""

import pytest

from test_helpers import (
    AWARDER,
    COORDINATOR,
    api_client,
    log_shifts,
    read_placement,
    read_partner,
    read_student,
    set_clock,
    setup_active_placement,
    setup_completed_placement,
    validate_success,
)

RIDGEVIEW = {
    "legal_name": "Ridgeview Manufacturing",
    "naics_code": "332710",
    "industry_sector": "MANUFACTURING",
}
ANA_PIKE = {
    "full_name": "Ana Pike",
    "birth_date": "2009-05-14",
    "student_learner_certificate": True,
}
HARBORVIEW = {
    "legal_name": "Harborview Health",
    "naics_code": "622110",
    "industry_sector": "HEALTHCARE",
}
RAVI_SEN = {
    "full_name": "Ravi Sen",
    "birth_date": "2008-01-10",
    "student_learner_certificate": False,
}


def _learner_wage_placement_with_three_shifts():
    """A learner-wage placement carrying three 3.33-hour shifts, which is what
    makes the two wage variants disagree."""
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="CTE-410",
        credit_hours_target=120.00,
        partner_overrides=RIDGEVIEW,
        student_overrides=ANA_PIKE,
        permit_class="MINOR_16_17",
        placement_overrides={
            "pay_classification": "PAID",
            "hourly_wage_cents": 1275,
            "stipend_total_cents": 0,
            "scheduled_weekly_hours": 12.00,
            "start_on": "2026-09-07",
            "end_on": "2026-12-18",
            "credit_target_credits": 1.00,
            "credit_award_mode": "COMPETENCY_BASED",
            "required_evaluation_cycles": 2,
            "transportation_mode": "PUBLIC_TRANSIT",
            "commute_round_trip_miles": 0.00,
        },
    )
    set_clock("2026-09-14T08:00:00Z")
    log_shifts(
        scenario,
        [
            ("2026-09-08", "08:00", "11:20"),
            ("2026-09-09", "08:00", "11:20"),
            ("2026-09-10", "08:00", "11:20"),
        ],
    )
    return scenario


def _competency_placement_completed_with_two_closed_cycles():
    """A completed placement with 48.00 verified hours and two closed cycles, so
    both credit models have real input to work from."""
    return setup_completed_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="CTE-220",
        credit_hours_target=90.00,
        shift_clock="2026-10-20T08:00:00Z",
        shifts=[
            ("2026-09-08", "08:00", "16:30", 30, False),
            ("2026-09-09", "08:00", "16:30", 30, False),
            ("2026-09-10", "08:00", "16:30", 30, False),
            ("2026-09-11", "08:00", "16:30", 30, False),
            ("2026-09-14", "08:00", "16:30", 30, False),
            ("2026-09-15", "08:00", "16:30", 30, False),
        ],
        ratings_per_cycle=[
            {
                "rating_technical": 5,
                "rating_communication": 4,
                "rating_reliability": 4,
                "rating_safety": 4,
                "rating_initiative": 4,
            },
            {
                "rating_technical": 4,
                "rating_communication": 5,
                "rating_reliability": 4,
                "rating_safety": 4,
                "rating_initiative": 4,
            },
        ],
        partner_overrides=HARBORVIEW,
        student_overrides=RAVI_SEN,
        permit_class="ADULT_18_PLUS",
        placement_overrides={
            "pay_classification": "PAID",
            "hourly_wage_cents": 1500,
            "stipend_total_cents": 0,
            "scheduled_weekly_hours": 16.00,
            "start_on": "2026-09-07",
            "end_on": "2026-12-18",
            "credit_target_credits": 1.00,
            "credit_award_mode": "COMPETENCY_BASED",
            "required_evaluation_cycles": 2,
            "transportation_mode": "DISTRICT_BUS",
            "commute_round_trip_miles": 0.00,
        },
    )


class TestWageVariantDivergence:
    def test_wage_preview_reports_both_variants_and_their_one_cent_variance(self):
        """The **provisional** variant rounds early: for each entry in turn, multiply
        that entry's `hours_worked` by the effective hourly rate and round the product
        half-up to a whole number of cents, then add those per-entry whole-cent amounts
        together. The **final** variant rounds late: add the `hours_worked` values of the
        same entries together and round that sum half-up to two decimal places, multiply
        the single total by the effective hourly rate, and round that one product half-up
        to a whole number of cents. Coordinators and compliance officers can preview the
        divergence before committing to a mode: the preview reports
        `provisional_wage_cents`, `final_wage_cents`, their `variance_cents` — the
        provisional figure minus the final figure — together with `total_verified_hours`
        and `logged_entry_count`.

        Design: Difficulty/dual_variant_calc/wage_provisional_vs_final_diverge_on_placement_money
        """
        scenario = _learner_wage_placement_with_three_shifts()

        preview = validate_success(
            api_client.get_wage_preview(scenario.placement_id, COORDINATOR)
        )

        assert float(preview["total_verified_hours"]) == pytest.approx(9.99)
        assert preview["logged_entry_count"] == 3
        assert preview["provisional_wage_cents"] == 12738
        assert preview["final_wage_cents"] == 12737
        assert preview["variance_cents"] == 1

    def test_placement_row_carries_both_live_wage_figures_before_any_settlement(self):
        """The placement carries both live figures at all times as
        `provisional_wage_cents` and `final_wage_cents`, refreshed on every timesheet
        write and every void. Settlement itself takes a `mode` of `PROVISIONAL` or
        `FINAL` and copies the corresponding figure into `settled_wage_cents`, recording
        the choice in `wage_settlement_mode`.

        Design: Difficulty/dual_variant_calc/wage_provisional_vs_final_diverge_on_placement_money
        """
        scenario = _learner_wage_placement_with_three_shifts()

        placement = read_placement(scenario.placement_id)

        assert float(placement["total_verified_hours"]) == pytest.approx(9.99)
        assert placement["provisional_wage_cents"] == 12738
        assert placement["final_wage_cents"] == 12737
        assert placement["settled_wage_cents"] == 0
        assert placement["wage_settlement_mode"] == "NONE"


class TestCreditVariantDivergence:
    def test_credit_preview_reports_what_each_award_model_would_grant(self):
        """Under `HOURS_BASED` credit is pure seat time: divide the placement's
        `total_verified_hours` by 45 — the clock hours the district treats as worth half
        a credit — discard any fraction of a block so that 44.99 verified hours earn
        nothing, multiply the whole number of blocks by 0.50, and take the smaller of
        that figure and the placement's `credit_target_credits`. A preview is available
        that reports what each model would grant: `hours_based_credits`,
        `competency_based_credits`, `mean_competency_score`, `closed_cycle_count` and
        `credit_eligible`.

        Design: Difficulty/dual_variant_calc/credit_hours_vs_competency_diverge_on_student_transcript
        """
        scenario = _competency_placement_completed_with_two_closed_cycles()

        preview = validate_success(
            api_client.get_credit_preview(scenario.placement_id, COORDINATOR)
        )

        assert float(preview["hours_based_credits"]) == pytest.approx(0.50)
        assert float(preview["competency_based_credits"]) == pytest.approx(0.85)
        assert float(preview["mean_competency_score"]) == pytest.approx(4.25)
        assert preview["closed_cycle_count"] == 2
        assert preview["credit_eligible"] is True

    def test_award_uses_the_declared_mode_and_lands_on_the_student_transcript(self):
        """Under `COMPETENCY_BASED` credit is pure mastery: take the placement's
        evaluation cycles whose `cycle_status` is `CLOSED`, in `cycle_index` ascending
        order, excluding `SUSPENDED` and `CANCELLED` cycles; add their
        `competency_score` values and divide by the number of those cycles, rounding
        half-up to two decimal places to get the mean; multiply the placement's
        `credit_target_credits` by that mean, divide by the maximum attainable rating of
        5.00, round half-up to two decimal places, and take the smaller of that figure
        and `credit_target_credits`. The award writes `credits_awarded` and
        `credit_awarded_by_user_id`, and adds the awarded figure to the student's
        `credits_earned_wbl`.

        Design: Difficulty/dual_variant_calc/credit_hours_vs_competency_diverge_on_student_transcript
        """
        scenario = _competency_placement_completed_with_two_closed_cycles()

        awarded = validate_success(
            api_client.award_placement_credit(scenario.placement_id, {}, AWARDER)
        )

        assert float(awarded["credits_awarded"]) == pytest.approx(0.85)
        assert float(awarded["total_verified_hours"]) == pytest.approx(48.00)

        student = read_student(scenario.student_id)
        assert float(student["credits_earned_wbl"]) == pytest.approx(0.85)
        assert float(student["ytd_wbl_hours"]) == pytest.approx(48.00)

        # The employer partner is untouched by a credit award.
        partner = read_partner(scenario.partner_id)
        assert partner["wage_liability_cents"] == 0
