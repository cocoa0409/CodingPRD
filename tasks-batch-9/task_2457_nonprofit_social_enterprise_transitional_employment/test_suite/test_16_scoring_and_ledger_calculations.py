"""Derived numbers: eligibility scores, conversion, period selection and the draw."""

import pytest

from test_helpers import (
    AllocationBasis,
    ApiErrorId,
    BusinessLineStatus,
    MouTier,
    ParticipantStatus,
    PriorityBand,
    ReferralStatus,
    RetentionMeasure,
    ScreeningDecision,
    ShiftAssignmentStatus,
    SubsidyPeriodStatus,
    WorkShiftStatus,
    assert_hours,
    assert_instant_equals,
    assert_per_hour_cents,
    assert_period_ledger,
    assert_ratio,
    assert_score,
    factories,
    fixtures,
    make_case_manager_headers,
    make_funder_analyst_headers,
    make_intake_specialist_headers,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_OCT_01, CLOCK_SEP_07, CLOCK_SEP_20

TWO_BARRIERS = ["JUSTICE_INVOLVED", "HOUSING_INSTABILITY"]
OCTOBER_PERIOD = {
    "period_start": "2026-10-01T00:00:00Z",
    "period_end": "2026-10-31T00:00:00Z",
}
OCTOBER_SHIFT_START = "2026-10-05T08:00:00Z"
OCTOBER_SHIFT_END = "2026-10-05T20:00:00Z"


def _midtown_candidate(api, hours_available_per_week=22):
    """A TIER_2 partner and one SUBMITTED candidate worth 39 unscaled points."""
    fixtures.set_clock(api, CLOCK_SEP_07)
    partner = fixtures.create_referral_partner(
        api,
        organization_name="Midtown Bridge",
        mou_tier=MouTier.TIER_2,
        referral_quota_per_period=5,
    )
    referral = fixtures.submit_referral(
        api,
        partner["id"],
        candidate_reference="CAND-201",
        declared_barrier_codes=list(TWO_BARRIERS),
        household_income_cents=200000,
        household_size=1,
        hours_available_per_week=hours_available_per_week,
    )
    return {"partner": partner, "referral": referral}


def _screen_eligible_on_hours(api, referral_id, hours_available_per_week):
    """Screen ELIGIBLE on the Midtown verified inputs at the given availability."""
    return api.screen_referral(
        referral_id,
        factories.screening_payload(
            ScreeningDecision.ELIGIBLE,
            verified_barrier_codes=list(TWO_BARRIERS),
            verified_household_income_cents=200000,
            verified_household_size=1,
            verified_hours_available_per_week=hours_available_per_week,
        ),
        make_intake_specialist_headers(),
    )


class TestPartnerConversionRate:
    """A partner's conversion rate is enrolments over everything they submitted."""

    def _partner_with_three_referrals(self, api):
        """Three submissions, of which only the first is screened ELIGIBLE."""
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        partner = fixtures.create_referral_partner(api)
        first = fixtures.create_eligible_referral(api, partner["id"])
        for reference in ("CAND-002", "CAND-003"):
            fixtures.submit_referral(
                api,
                partner["id"],
                candidate_reference=reference,
                declared_barrier_codes=["JUSTICE_INVOLVED"],
            )
        return {"business_line": line, "partner": partner, "referral": first}

    def test_one_enrolment_out_of_three_submissions_is_a_third(self, api):
        """The denominator is every referral, not just the eligible ones.

        "`conversion_rate` is `enrolled_referral_count` divided by
        `referrals_submitted_count`, rounded half up to four decimal places, and
        is `null` — never 0 — while the partner has submitted nothing at all."

        Design: Corner/calculations/partner_conversion_rate_after_first_enrollment
        """
        program = self._partner_with_three_referrals(api)

        participant = fixtures.enroll_participant(
            api, program["business_line"]["id"], program["referral"]["id"]
        )

        assert participant["status"] == ParticipantStatus.TRANSITIONAL_EMPLOYED
        assert_instant_equals(participant["enrolled_at"], CLOCK_SEP_07, "enrolled_at")

        partner = fixtures.read_referral_partner(api, program["partner"]["id"])
        assert partner["referrals_submitted_count"] == 3
        assert partner["enrolled_referral_count"] == 1
        assert_ratio(partner["conversion_rate"], 0.3333, "conversion_rate")

    def test_the_enrolled_referral_keeps_its_top_band_score(self, api):
        """Three barriers, deep poverty and full availability under TIER_1.

        "`priority_band` follows from the rounded score — `BAND_A` at 70.00 or
        above, `BAND_B` from 50.00 up to but not including 70.00, and `BAND_C`
        below that."

        Design: Corner/calculations/partner_conversion_rate_after_first_enrollment
        """
        program = self._partner_with_three_referrals(api)
        fixtures.enroll_participant(
            api, program["business_line"]["id"], program["referral"]["id"]
        )

        referral = fixtures.read_referral(api, program["referral"]["id"])
        assert referral["status"] == ReferralStatus.ENROLLED
        assert_score(referral["eligibility_score"], 100.10, "eligibility_score")
        assert referral["priority_band"] == PriorityBand.BAND_A


class TestEligibilityScoreFloor:
    """One point of availability decides whether a candidate may enrol."""

    def test_a_forty_nine_point_score_is_refused(self, api):
        """The floor is checked on the rounded score, and 49.00 is below it.

        "The floor comparison uses the **rounded** score, so a raw 49.995 that
        rounds to 50.00 passes while a raw 49.994 that rounds to 49.99 fails, and
        any of the three failures reports `ERR_ELIGIBILITY_SCORE_BELOW_FLOOR`."

        Design: Corner/calculations/eligibility_score_floor_boundary_50_00_vs_49_00
        """
        referral = _midtown_candidate(api)["referral"]

        response = _screen_eligible_on_hours(api, referral["id"], 21)

        validate_error(response, ApiErrorId.ERR_ELIGIBILITY_SCORE_BELOW_FLOOR, 422)

        stored = fixtures.read_referral(api, referral["id"])
        assert stored["status"] == ReferralStatus.SUBMITTED
        assert stored["eligibility_score"] is None
        assert stored["screened_at"] is None

    def test_a_fifty_point_score_sits_exactly_on_the_floor(self, api):
        """At the floor the eligible branch is taken.

        "The **eligible** branch, `SUBMITTED → ELIGIBLE` or `WAITLISTED →
        ELIGIBLE`, is the only one that enforces floors: it requires at least one
        verified barrier code, `hours_available_per_week` of at least 20, and an
        `eligibility_score` of at least 50.00."

        Design: Corner/calculations/eligibility_score_floor_boundary_50_00_vs_49_00
        """
        referral = _midtown_candidate(api)["referral"]

        referral = validate_success(_screen_eligible_on_hours(api, referral["id"], 22))

        assert referral["status"] == ReferralStatus.ELIGIBLE
        assert_score(referral["eligibility_score"], 50.00, "eligibility_score")
        assert referral["priority_band"] == PriorityBand.BAND_B
        assert_ratio(referral["fpl_ratio"], 1.5905, "fpl_ratio")


class TestPartnerTierMultiplier:
    """One point sum, three tiers, three scores."""

    def _one_candidate_under_each_tier(self, api):
        """The same candidate handle submitted by three partners at once."""
        fixtures.set_clock(api, CLOCK_SEP_07)
        referrals = {}
        for tier, name in (
            (MouTier.TIER_1, "Tier One Works"),
            (MouTier.TIER_2, "Tier Two Works"),
            (MouTier.TIER_3, "Tier Three Works"),
        ):
            partner = fixtures.create_referral_partner(
                api,
                organization_name=name,
                mou_tier=tier,
                referral_quota_per_period=5,
            )
            referrals[tier] = fixtures.submit_referral(
                api,
                partner["id"],
                candidate_reference="CAND-301",
                declared_barrier_codes=list(TWO_BARRIERS),
                household_income_cents=200000,
                household_size=1,
                hours_available_per_week=22,
            )
        return referrals

    @pytest.mark.parametrize(
        "tier, expected_score, expected_band",
        [
            (MouTier.TIER_1, 55.00, PriorityBand.BAND_B),
            (MouTier.TIER_2, 50.00, PriorityBand.BAND_B),
            (MouTier.TIER_3, 45.00, PriorityBand.BAND_C),
        ],
    )
    def test_the_tier_scales_the_whole_point_sum(
        self, api, tier, expected_score, expected_band
    ):
        """The multiplier lands on the integer sum, once.

        "Fifth, the partner multiplier, taken from the referring partner's
        `mou_tier`: `TIER_1` gives 1.10, `TIER_2` gives 1.00, and `TIER_3` gives
        0.90."

        Design: Corner/calculations/tier_multiplier_changes_the_same_point_sum
        """
        referrals = self._one_candidate_under_each_tier(api)

        decision = (
            ScreeningDecision.WAITLISTED
            if expected_score < 50.00
            else ScreeningDecision.ELIGIBLE
        )
        response = api.screen_referral(
            referrals[tier]["id"],
            factories.screening_payload(
                decision,
                verified_barrier_codes=list(TWO_BARRIERS),
                verified_household_income_cents=200000,
                verified_household_size=1,
                verified_hours_available_per_week=22,
            ),
            make_intake_specialist_headers(),
        )
        referral = validate_success(response)

        assert_score(referral["eligibility_score"], expected_score, "eligibility_score")
        assert referral["priority_band"] == expected_band
        assert_ratio(referral["fpl_ratio"], 1.5905, "fpl_ratio")

    def test_the_multiplier_never_reaches_the_poverty_ratio(self, api):
        """The ratio is a property of the household, not of the partner.

        "`fpl_ratio` is the verified monthly `household_income_cents` multiplied
        by twelve, divided by that annual base, rounded half up to four decimal
        places."

        Design: Corner/calculations/tier_multiplier_changes_the_same_point_sum
        """
        referrals = self._one_candidate_under_each_tier(api)

        for tier, decision in (
            (MouTier.TIER_1, ScreeningDecision.ELIGIBLE),
            (MouTier.TIER_2, ScreeningDecision.ELIGIBLE),
            (MouTier.TIER_3, ScreeningDecision.WAITLISTED),
        ):
            referral = fixtures.screen_referral(
                api,
                referrals[tier]["id"],
                decision,
                verified_barrier_codes=list(TWO_BARRIERS),
                verified_household_income_cents=200000,
                verified_household_size=1,
                verified_hours_available_per_week=22,
            )
            assert_ratio(referral["fpl_ratio"], 1.5905, "fpl_ratio")


class TestCompletionPeriodSelection:
    """The period a wage cost lands in is chosen by the shift, not by the clock."""

    def _september_shift_left_behind_a_closed_period(self, api):
        """A September shift seated only after September has been closed."""
        program = fixtures.enrolled_participant_program(api)
        september_shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            "2026-09-07T08:00:00Z",
            "2026-09-07T20:00:00Z",
        )
        fixtures.set_clock(api, CLOCK_OCT_01)
        fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 500000
        )
        october_period = fixtures.create_open_subsidy_period(
            api, program["business_line"]["id"], **OCTOBER_PERIOD
        )
        september_seat = fixtures.seat_participant(
            api, september_shift["id"], program["participant"]["id"]
        )
        october_shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            OCTOBER_SHIFT_START,
            OCTOBER_SHIFT_END,
        )
        october_seat = fixtures.seat_participant(
            api, october_shift["id"], program["participant"]["id"]
        )
        fixtures.set_clock(api, OCTOBER_SHIFT_END)
        program["september_shift"] = september_shift
        program["september_seat"] = september_seat
        program["october_period"] = october_period
        program["october_shift"] = october_shift
        program["october_seat"] = october_seat
        return program

    def test_a_shift_anchored_in_a_closed_period_cannot_be_completed(self, api):
        """The open October period does not cover a September shift start.

        "The anchor instant is the shift's `starts_at` for an assignment
        completion and the logical clock's current instant for a support-activity
        delivery."

        Design: Corner/calculations/completion_selects_open_period_by_shift_start_not_now
        """
        program = self._september_shift_left_behind_a_closed_period(api)

        response = api.complete_shift_assignment(
            program["september_seat"]["id"],
            factories.completion_payload(actual_hours=12.000),
            make_case_manager_headers(),
        )

        validate_error(response, ApiErrorId.ERR_NO_OPEN_SUBSIDY_PERIOD, 409)

        assignment = fixtures.read_shift_assignment(
            api, program["september_seat"]["id"]
        )
        assert assignment["status"] == ShiftAssignmentStatus.ASSIGNED
        assert assignment["wage_cost_cents"] is None
        shift = fixtures.read_work_shift(api, program["september_shift"]["id"])
        assert shift["status"] == WorkShiftStatus.SCHEDULED

    def test_the_october_shift_posts_into_the_october_period(self, api):
        """The one open period covering the anchor takes the whole wage cost.

        "The period's `trainee_hours` is the sum of `actual_hours` over
        `COMPLETED` assignments whose shift belongs to this line and whose shift
        `starts_at` falls inside the closed period interval, rounded half up to
        three decimal places — note that the shift must *start* inside the
        period, not merely overlap it."

        Design: Corner/calculations/completion_selects_open_period_by_shift_start_not_now
        """
        program = self._september_shift_left_behind_a_closed_period(api)

        completed = fixtures.complete_assignment(
            api, program["october_seat"]["id"], 12.000
        )

        assert completed["status"] == ShiftAssignmentStatus.COMPLETED
        assert completed["wage_cost_cents"] == 19800

        period = fixtures.read_subsidy_period(api, program["october_period"]["id"])
        assert_period_ledger(period, 4570, 15230, 19800)
        assert_ratio(period["mission_share"], 0.2308, "mission_share")
        assert_hours(period["trainee_hours"], 12.000, "trainee_hours")
        assert_per_hour_cents(
            period["true_cost_per_trainee_hour_cents"],
            1650.00,
            "true_cost_per_trainee_hour_cents",
        )
        assert_per_hour_cents(
            period["subsidy_per_trainee_hour_cents"],
            380.83,
            "subsidy_per_trainee_hour_cents",
        )


class TestSubsidyDrawTierBoundary:
    """Eight cents of revenue decide which subsidy tier a period draws on."""

    def _two_periods_each_holding_one_twelve_hour_shift(self, api):
        """September and October, each with a single completed shift."""
        program = fixtures.completed_shift_program(api)
        october_period = fixtures.create_open_subsidy_period(
            api, program["business_line"]["id"], **OCTOBER_PERIOD
        )
        october_shift = fixtures.create_work_shift(
            api,
            program["business_line"]["id"],
            OCTOBER_SHIFT_START,
            OCTOBER_SHIFT_END,
        )
        october_seat = fixtures.seat_participant(
            api, october_shift["id"], program["participant"]["id"]
        )
        fixtures.set_clock(api, OCTOBER_SHIFT_END)
        fixtures.complete_assignment(api, october_seat["id"], 12.000)
        fixtures.set_clock(api, "2026-11-01T00:00:00Z")
        program["october_period"] = october_period
        return program

    def test_a_margin_of_exactly_two_tenths_buys_the_cheapest_tier(self, api):
        """The tier is read off the rounded margin, and 0.2000 reaches the top band.

        "`subsidy_rate` is chosen from that **rounded** margin: 0.50 when
        `margin_pct` is at least 0.2000, 0.70 when `margin_pct` is at least
        0.0500 but below 0.2000, and 0.90 when `margin_pct` is below 0.0500."

        Design: Corner/calculations/subsidy_draw_tier_boundary_margin_exactly_0_2000
        """
        program = self._two_periods_each_holding_one_twelve_hour_shift(api)

        closed = fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 19038
        )

        assert closed["status"] == SubsidyPeriodStatus.CLOSED
        assert_ratio(closed["mission_share"], 0.2308, "mission_share")
        assert_period_ledger(closed, 4570, 15230, 19800)
        assert_ratio(closed["margin_pct"], 0.2000, "margin_pct")
        assert closed["subsidy_rate"] == pytest.approx(0.50, abs=0.005)
        assert closed["subsidy_draw_cents"] == 2285

    def test_eight_cents_less_revenue_costs_a_whole_tier(self, api):
        """The draw is the consequence of the margin, never an input to it.

        "`subsidy_draw_cents` is then `mission_cost_cents` multiplied by
        `subsidy_rate`, rounded half up to whole cents."

        Design: Corner/calculations/subsidy_draw_tier_boundary_margin_exactly_0_2000
        """
        program = self._two_periods_each_holding_one_twelve_hour_shift(api)
        fixtures.close_subsidy_period(
            api, program["subsidy_period"]["id"], AllocationBasis.HOURS, 19038
        )

        closed = fixtures.close_subsidy_period(
            api, program["october_period"]["id"], AllocationBasis.HOURS, 19030
        )

        assert_ratio(closed["margin_pct"], 0.1997, "margin_pct")
        assert closed["subsidy_rate"] == pytest.approx(0.70, abs=0.005)
        assert closed["subsidy_draw_cents"] == 3199

        line = fixtures.read_business_line(api, program["business_line"]["id"])
        assert line["cumulative_subsidy_cents"] == 5484
        assert line["status"] == BusinessLineStatus.LAUNCHED


class TestOutcomeSummaryDefaultWindow:
    """Asked without a window, the report answers from launch to now."""

    def _launched_line_with_no_activity(self, api):
        fixtures.set_clock(api, CLOCK_SEP_07)
        line = fixtures.create_launched_business_line(api)
        fixtures.set_clock(api, CLOCK_SEP_20)
        return line

    def test_the_window_runs_from_launch_to_the_logical_clock(self, api):
        """Both ends of the window have documented defaults.

        "The outcome summary answers for one business line over a closed window
        from `period_start` through `period_end`, both at `00:00:00Z`, defaulting
        to the line's `launched_at` through the logical clock's current instant
        when either is omitted."

        Design: Corner/calculations/outcome_summary_defaults_window_to_launch_and_now
        """
        line = self._launched_line_with_no_activity(api)

        summary = validate_success(
            api.get_outcome_summary(line["id"], make_funder_analyst_headers())
        )

        assert summary["business_line_id"] == line["id"]
        assert_instant_equals(summary["period_start"], CLOCK_SEP_07, "period_start")
        assert_instant_equals(summary["period_end"], CLOCK_SEP_20, "period_end")
        assert summary["retention_measure"] == RetentionMeasure.COHORT_BASED

    def test_an_empty_cohort_reports_null_rates_rather_than_zero(self, api):
        """An empty denominator is null, and the counts are still integers.

        "`placement_rate` is `placed_count` divided by `enrolled_count`, rounded
        half up to four decimals, and null when the cohort is empty."

        Design: Corner/calculations/outcome_summary_defaults_window_to_launch_and_now
        """
        line = self._launched_line_with_no_activity(api)

        summary = validate_success(
            api.get_outcome_summary(line["id"], make_funder_analyst_headers())
        )

        assert summary["enrolled_count"] == 0
        assert summary["placed_count"] == 0
        assert summary["retention_denominator"] == 0
        assert summary["retention_numerator"] == 0
        assert summary["verified_placement_count"] == 0
        assert summary["placement_rate"] is None
        assert summary["retention_rate"] is None
        assert summary["average_wage_progression_pct"] is None
