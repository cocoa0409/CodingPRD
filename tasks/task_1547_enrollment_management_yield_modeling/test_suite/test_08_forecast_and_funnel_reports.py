"""Yield forecasting (both variants) and the source-attribution funnel
report, plus the cycle admit rate."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_aid_offer,
    assign_and_submit_review,
    create_admitted_application,
    create_aid_offer,
    create_applicant,
    create_application_for_new_applicant,
    setup_open_cycle_with_program,
    submit_application,
    transition_application,
    validate_success,
)

MANAGER = TEST_USERS["enrollment_manager_headers"]
OFFICER = TEST_USERS["admissions_officer_headers"]


class TestYieldForecastVariants:
    def _three_admitted_with_aid_on_first(self, api):
        """Scores 92 / 85 / 60; the score-92 applicant accepts a MERIT offer
        (0.35 tier -> 1750000 -> coverage 0.35)."""
        setup = setup_open_cycle_with_program(
            name="CS", capacity_seats=10, target_enrollment=5,
            scholarship_budget_cents=10_000_000)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        pair_one = create_admitted_application(cycle_id, program_id,
                                               academic_score=92)
        create_admitted_application(cycle_id, program_id, academic_score=85)
        create_admitted_application(cycle_id, program_id, academic_score=60)
        offer = create_aid_offer(pair_one["application"], "MERIT")
        accept_aid_offer(offer["id"], pair_one["applicant"]["id"])
        return setup

    def test_historical_band_projection(self, api):
        """PRD 3.9: "Under the historical-band variant, each pipeline
        application's probability comes from its `academic_score` alone: 0.65
        when the score is at least 90, 0.45 when the score is at least 70 but
        below 90, and 0.25 when the score is below 70."
        PRD 3.9: "The `projected_enrollment` is the enrolled base plus the
        deposited base plus the sum of the pipeline probabilities, rounded
        half-up to a whole number."

        Design: Difficulty/dual_variant_calc/yield_forecast_aid_adjusted_lifts_projection
        """
        setup = self._three_admitted_with_aid_on_first(api)
        forecast = validate_success(api.get_cycle_forecast(
            setup["cycle"]["id"], MANAGER,
            params={"variant": "historical_band"}))
        assert forecast["variant"] == "historical_band"
        assert forecast["projected_enrollment"] == 1, (
            "0.65 (92) + 0.45 (85) + 0.25 (60) = 1.35 -> round-half-up 1; "
            "financial aid is ignored under this variant")
        assert forecast["admitted_count"] == 3
        assert forecast["deposited_count"] == 0
        assert forecast["enrolled_count"] == 0

    def test_aid_adjusted_projection_lifts(self, api):
        """PRD 3.9: "Under the aid-adjusted variant, a coverage ratio is
        computed per application — its `aid_accepted_cents` divided by its
        program's `tuition_cents`, rounded half-up to four decimals, and 0
        when the applicant holds no accepted aid — and the band probability
        is scaled by one plus the coverage ratio, capped at 1.0, and rounded
        half-up to four decimals; identical inputs therefore yield a
        projection that is higher whenever any admitted applicant holds
        accepted aid."

        Design: Difficulty/dual_variant_calc/yield_forecast_aid_adjusted_lifts_projection
        """
        setup = self._three_admitted_with_aid_on_first(api)
        historical = validate_success(api.get_cycle_forecast(
            setup["cycle"]["id"], MANAGER,
            params={"variant": "historical_band"}))
        adjusted = validate_success(api.get_cycle_forecast(
            setup["cycle"]["id"], MANAGER,
            params={"variant": "aid_adjusted"}))
        assert adjusted["variant"] == "aid_adjusted"
        assert adjusted["projected_enrollment"] == 2, (
            "0.65*(1+0.35) = 0.8775 for the aided 92-score applicant, plus "
            "0.45 + 0.25 = 1.5775 -> round-half-up 2")
        assert adjusted["projected_enrollment"] != \
            historical["projected_enrollment"], \
            "The same pipeline projects higher once accepted aid is levered"

    def test_forecast_default_variant_is_historical(self, api):
        """PRD 3.9: "The yield forecast takes an optional `variant` query
        parameter — `historical_band` by default, or `aid_adjusted`"
        PRD 3.9: "The response reports the `variant`, the
        `projected_enrollment`, the cycle's `admit_rate` alongside, and the
        three counts `admitted_count`, `deposited_count`, and
        `enrolled_count`."

        Design: Corner/endpoints/forecast_default_variant_is_historical
        """
        setup = setup_open_cycle_with_program(name="DEF")
        forecast = validate_success(api.get_cycle_forecast(
            setup["cycle"]["id"], MANAGER))
        assert forecast["variant"] == "historical_band", \
            "Omitting the variant parameter defaults to historical_band"
        assert forecast["projected_enrollment"] == 0, \
            "Empty pipeline and zero bases project zero"
        assert forecast["admitted_count"] == 0

    def test_forecast_pipeline_excludes_withdrawn(self, api):
        """PRD 3.9: "the pipeline is exactly the cycle's applications
        currently in `ADMITTED`, with applications in `SUBMITTED`,
        `IN_REVIEW`, `COMMITTEE_REVIEW`, `DECISION_PENDING`, `WAITLISTED`,
        `DENIED`, `WITHDRAWN`, or `MELTED` never entering it."

        Design: Corner/calculations/forecast_pipeline_excludes_withdrawn
        """
        setup = setup_open_cycle_with_program(name="FIL", capacity_seats=5,
                                              target_enrollment=3)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        create_admitted_application(cycle_id, program_id, academic_score=85)
        withdrawn = create_admitted_application(cycle_id, program_id,
                                                academic_score=85)
        transition_application(withdrawn["application"]["id"], "WITHDRAWN")

        forecast = validate_success(api.get_cycle_forecast(
            cycle_id, OFFICER, params={"variant": "historical_band"}))
        assert forecast["projected_enrollment"] == 0, (
            "Only the still-ADMITTED application contributes: "
            "round-half-up(0.45) = 0; the WITHDRAWN one never enters")
        assert forecast["admitted_count"] == 1


class TestFunnelReport:
    def _two_source_funnel(self, api):
        """Six PURCHASED_LIST inquiries (one applies) and three WEB_FORM
        inquiries (one applies)."""
        setup = setup_open_cycle_with_program(name="HIS", capacity_seats=10,
                                              target_enrollment=5)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        for idx in range(6):
            applicant = create_applicant(cycle_id,
                                         inquiry_source="PURCHASED_LIST")
            if idx == 0:
                submit_application(cycle_id, program_id, applicant["id"],
                                   academic_score=80)
        for idx in range(3):
            applicant = create_applicant(cycle_id, inquiry_source="WEB_FORM")
            if idx == 0:
                submit_application(cycle_id, program_id, applicant["id"],
                                   academic_score=80)
        return setup

    def test_funnel_overall_rate_rounded_once(self, api):
        """PRD 3.9: "The report's `overall_conversion_rate` is computed from
        the unrounded totals — total applied across all sources divided by
        total inquiries — and rounded half-up to four decimals exactly once;
        it is deliberately not an average of the per-source rounded rates"

        Design: Difficulty/combinatorial_formula/funnel_overall_rate_rounded_once_not_averaged
        """
        setup = self._two_source_funnel(api)
        report = validate_success(
            api.get_cycle_funnel_report(setup["cycle"]["id"], OFFICER))
        assert report["inquiry_count"] == 9
        assert report["applied_count"] == 2
        assert report["overall_conversion_rate"] == pytest.approx(
            0.2222, abs=1e-6), (
            "round(2/9, 4) = 0.2222 computed once from the unrounded "
            "totals — not 0.2500, the mean of the rounded per-source rates")

    def test_funnel_report_covers_every_source(self, api):
        """PRD 3.9: "For each of the five `inquiry_source` values —
        `WEB_FORM`, `CAMPUS_VISIT`, `COLLEGE_FAIR`, `REFERRAL`, and
        `PURCHASED_LIST` — it counts the cycle's applicants attributed to
        that source and how many of them have reached `funnel_stage` of
        `APPLIED`, emitting one row per source with a per-source conversion
        rate of applied divided by inquiries, rounded half-up to four
        decimals, and reported as 0.0 when the source has no inquiries."

        Design: Difficulty/combinatorial_formula/funnel_overall_rate_rounded_once_not_averaged
        """
        setup = self._two_source_funnel(api)
        report = validate_success(
            api.get_cycle_funnel_report(setup["cycle"]["id"], MANAGER))
        assert len(report["rows"]) == 5, \
            "One row is emitted per inquiry source, even with zero inquiries"


class TestCycleAdmitRate:
    def test_cycle_admit_rate_computed(self, api):
        """PRD 3.1: "The `decisioned_count` counts every application that has
        ever received a decision — any application that ever reached
        `ADMITTED` (including ones that later moved to `DEPOSITED`,
        `ENROLLED`, `MELTED`, or withdrew after admission) plus every
        application in `DENIED`."
        PRD 3.1: "From these the cycle reports `admit_rate`: the count of
        applications that ever reached `ADMITTED` divided by
        `decisioned_count`, expressed to four decimal places round-half-up"

        Design: Corner/calculations/cycle_admit_rate_computed
        """
        setup = setup_open_cycle_with_program(name="ADM", capacity_seats=5,
                                              target_enrollment=3)
        cycle_id = setup["cycle"]["id"]
        program_id = setup["program"]["id"]
        create_admitted_application(cycle_id, program_id, academic_score=90)

        denied = create_application_for_new_applicant(cycle_id, program_id,
                                                      academic_score=55)
        app_id = denied["application"]["id"]
        transition_application(app_id, "IN_REVIEW")
        assign_and_submit_review(app_id, "reader-1", score=55,
                                 recommendation="DENY")
        assign_and_submit_review(app_id, "reader-2", score=55,
                                 recommendation="DENY")
        transition_application(app_id, "DECISION_PENDING")
        denied_app = transition_application(app_id, "DENIED")
        assert denied_app["status"] == "DENIED"

        cycle = validate_success(api.get_cycle(cycle_id, MANAGER))
        assert cycle["decisioned_count"] == 2, "One admitted, one denied"
        assert cycle["admit_rate"] == pytest.approx(0.5, abs=1e-6), \
            "1 ever-admitted / 2 decisioned = 0.5"
