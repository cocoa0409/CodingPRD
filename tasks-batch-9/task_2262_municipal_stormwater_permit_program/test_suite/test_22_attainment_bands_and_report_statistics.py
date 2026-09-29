"""Measurable-goal attainment, its gates, and the statistics compilation freezes."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import MANAGER_ONE, OPERATIONS_HEADERS

OUTFALL_FIELDS = {
    "receiving_water": "Mill Creek",
    "drainage_area_acres": 45.00,
    "priority_tier": "HIGH",
    "baseline_concentration_mg_per_l": 0.45,
    "design_runoff_kl": 20000,
    "sweeping_capacity_lane_miles_per_month": 40.00,
}


def _report_progress_as_supervisor(measure_id, actual):
    """Report a measurable-goal actual as the operations supervisor."""
    return validate_success(
        api_client.report_measure_progress(
            measure_id, factories.report_progress_payload(actual), OPERATIONS_HEADERS
        )
    )


class TestAttainmentBandsAndTheGatesAboveThem:
    """The band edges, the zero-actual edge out of PENDING, and a flag gate."""

    @pytest.fixture
    def uncovered_salt_program(self):
        """An ACTIVE term whose municipal operations salt pile is uncovered."""
        return fx.setup_active_program(
            outfall_codes=("OF-01",),
            funding_target_cents=25000,
            measure_overrides={"MUNICIPAL_OPERATIONS": {"salt_storage_covered": False}},
            outfall_overrides=dict(OUTFALL_FIELDS),
        )

    def test_01_seventy_five_percent_is_the_inclusive_lower_edge_of_on_track(
        self, uncovered_salt_program
    ):
        """Nine of twelve education events sit exactly on the band edge.

        PRD: "`attainment_pct` is 0.00 when `measurable_goal_target` is 0; otherwise it
        is 100 multiplied by `measurable_goal_actual`, divided by `measurable_goal_target`,
        rounded to 2 decimal places." And: "If `attainment_pct` is at least 75.00, the
        result is `ON_TRACK`."

        Design: Corner/calculations/goal_attainment_bands_and_gates_including_the_pending_to_behind_edge
        """
        measure = fx.report_progress(
            uncovered_salt_program["measures"]["PUBLIC_EDUCATION"]["id"], 9
        )

        assert measure["attainment_pct"] == pytest.approx(75.00, abs=0.01), (
            f"nine of twelve is 75.00 percent, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "ON_TRACK", "the edge belongs to the band"
        assert measure["last_progress_reported_at"] == "2026-08-01T00:00:00Z", (
            "the report instant comes from the logical clock"
        )

    def test_02_the_full_target_is_met(self, uncovered_salt_program):
        """Twelve of twelve reaches the top band.

        PRD: "If `attainment_pct` is at least 100.00, the result is `MET`."

        Design: Corner/calculations/goal_attainment_bands_and_gates_including_the_pending_to_behind_edge
        """
        measure_id = uncovered_salt_program["measures"]["PUBLIC_EDUCATION"]["id"]
        fx.report_progress(measure_id, 9)

        measure = fx.report_progress(measure_id, 12)

        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            f"twelve of twelve is 100.00 percent, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "MET", "the target is met"

    def test_03_the_actual_is_absolute_so_a_lower_number_falls_back_to_behind(
        self, uncovered_salt_program
    ):
        """Eight of twelve rounds half up to 66.67 and lands under both bands.

        PRD: "The manager or a `MunicipalOperationsSupervisor` reports progress by
        supplying `measurable_goal_actual`, which requires the measure's `status` to be
        `ACTIVE`; the call stamps `last_progress_reported_at` from the logical clock."
        And: "Every rounding in this system is **round half up**, and the number of
        decimal places is fixed per quantity." And: "Otherwise the result is `BEHIND`."

        Design: Corner/calculations/goal_attainment_bands_and_gates_including_the_pending_to_behind_edge
        """
        measure_id = uncovered_salt_program["measures"]["PUBLIC_EDUCATION"]["id"]
        fx.report_progress(measure_id, 9)
        fx.report_progress(measure_id, 12)

        measure = fx.report_progress(measure_id, 8)

        assert measure["measurable_goal_actual"] == pytest.approx(8.00, abs=0.01), (
            "the reported figure replaces the earlier one outright"
        )
        assert measure["attainment_pct"] == pytest.approx(66.67, abs=0.01), (
            f"66.666... rounds half up to 66.67, got {measure['attainment_pct']}"
        )
        assert measure["goal_status"] == "BEHIND", "neither band is reached"

    def test_04_reporting_zero_moves_a_measure_out_of_pending_into_behind(
        self, uncovered_salt_program
    ):
        """The pending rule needs a null timestamp, and the report has just set one.

        PRD: "The manager or a `MunicipalOperationsSupervisor` reports progress by
        supplying `measurable_goal_actual`, which requires the measure's `status` to be
        `ACTIVE`; the call stamps `last_progress_reported_at` from the logical clock."
        And: "If `last_progress_reported_at` is null and `measurable_goal_actual` is 0,
        the result is `PENDING`." And: "Otherwise the result is `BEHIND`."

        Design: Corner/calculations/goal_attainment_bands_and_gates_including_the_pending_to_behind_edge
        """
        monitoring = uncovered_salt_program["measures"]["MONITORING"]
        assert monitoring["goal_status"] == "PENDING", "an unreported measure is pending"

        measure = _report_progress_as_supervisor(monitoring["id"], 0)

        assert measure["measurable_goal_actual"] == pytest.approx(0.00, abs=0.01), (
            "the reported actual is zero"
        )
        assert measure["attainment_pct"] == pytest.approx(0.00, abs=0.01), (
            "zero of four is zero percent"
        )
        assert measure["last_progress_reported_at"] == "2026-08-01T00:00:00Z", (
            "the report stamped its instant, which is what ends PENDING"
        )
        assert measure["goal_status"] == "BEHIND", (
            "a reported zero is behind, not pending"
        )

    def test_05_the_sweeping_mirror_fills_the_actual_but_the_flag_gate_still_holds(
        self, uncovered_salt_program
    ):
        """A hundred percent attainment is still BEHIND while the salt pile is open.

        PRD: "Each accepted run mirrors the term-wide lane-mile total into the
        `MUNICIPAL_OPERATIONS` control measure's `swept_lane_miles_ytd` — the sum of
        `lane_miles_swept` across the `sweeping_runs` of every `ACTIVE` outfall in the
        term — and copies that same figure into that measure's `measurable_goal_actual`,
        then recomputes its `attainment_pct` and `goal_status` and the term's posture."
        And: "For the `MUNICIPAL_OPERATIONS` measure, if either `salt_storage_covered` is
        false or `fleet_wash_recycle` is false, the result is `BEHIND`."

        Design: Corner/calculations/goal_attainment_bands_and_gates_including_the_pending_to_behind_edge
        """
        fx.append_sweeping_run(
            uncovered_salt_program["outfalls"]["OF-01"]["id"],
            "2026-08-01",
            "2026-08-10",
            20.00,
        )

        measure = fx.read_measure(
            uncovered_salt_program["measures"]["MUNICIPAL_OPERATIONS"]["id"]
        )
        assert measure["swept_lane_miles_ytd"] == pytest.approx(20.00, abs=0.01), (
            "the term-wide total is mirrored onto the measure"
        )
        assert measure["measurable_goal_actual"] == pytest.approx(20.00, abs=0.01), (
            "the same figure becomes the actual, with nobody reporting it"
        )
        assert measure["attainment_pct"] == pytest.approx(100.00, abs=0.01), (
            "twenty of twenty is 100.00 percent"
        )
        assert measure["goal_status"] == "BEHIND", (
            "the gate wins outright over the band"
        )

    def test_06_three_behind_measures_make_the_term_non_compliant(
        self, uncovered_salt_program
    ):
        """The census counts BEHIND measures, whatever put them there.

        PRD: "`behind_measure_count` is the number of control measures of the term whose
        `status` is `ACTIVE` and whose `goal_status` is `BEHIND`." And: "If
        `behind_measure_count` is two or more, or if `behind_measure_count` is at least
        one while `exceeding_outfall_count` is also at least one, `compliance_posture`
        becomes `NON_COMPLIANT`."

        Design: Corner/calculations/goal_attainment_bands_and_gates_including_the_pending_to_behind_edge
        """
        measures = uncovered_salt_program["measures"]
        fx.report_progress(measures["PUBLIC_EDUCATION"]["id"], 9)
        fx.report_progress(measures["PUBLIC_EDUCATION"]["id"], 12)
        fx.report_progress(measures["PUBLIC_EDUCATION"]["id"], 8)
        _report_progress_as_supervisor(measures["MONITORING"]["id"], 0)
        fx.append_sweeping_run(
            uncovered_salt_program["outfalls"]["OF-01"]["id"],
            "2026-08-01",
            "2026-08-10",
            20.00,
        )

        term = fx.read_term(uncovered_salt_program["term_id"])
        assert term["behind_measure_count"] == 3, (
            "education, monitoring and municipal operations are all behind, got "
            f"{term['behind_measure_count']}"
        )
        assert term["exceeding_outfall_count"] == 0, "no outfall was ever assessed"
        assert term["compliance_posture"] == "NON_COMPLIANT", (
            "two or more behind measures is the non-compliant threshold"
        )

        untouched = fx.read_measure(measures["POST_CONSTRUCTION"]["id"])
        assert untouched["goal_status"] == "PENDING", (
            "a measure nobody reported on is still pending"
        )
        assert untouched["last_progress_reported_at"] is None, "no instant was stamped"
        assert untouched["measurable_goal_actual"] == pytest.approx(0.00, abs=0.01), (
            "its actual was never filled"
        )


class TestCompilationCountsTheWindowAndRoundsTheIndexOnce:
    """One program with something in every statistic, frozen in one call."""

    @pytest.fixture
    def reported_program(self):
        """Six reported measures, two screenings, one finalized inspection, one assessment."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01",),
            funding_target_cents=25000,
            outfall_overrides=dict(OUTFALL_FIELDS),
        )
        measures = program["measures"]
        fx.report_progress(measures["PUBLIC_EDUCATION"]["id"], 9)
        fx.report_progress(measures["ILLICIT_DISCHARGE"]["id"], 20)
        fx.report_progress(measures["CONSTRUCTION_RUNOFF"]["id"], 24)
        fx.report_progress(measures["POST_CONSTRUCTION"]["id"], 10)
        fx.report_progress(measures["MONITORING"]["id"], 2)
        outfall_id = program["outfalls"]["OF-01"]["id"]
        fx.append_sweeping_run(outfall_id, "2026-08-01", "2026-08-10", 20.00)
        fx.record_screening(
            outfall_id, "2026-07-01T08:00:00Z", dry_weather_flow_present=False
        )
        fx.record_screening(
            outfall_id, "2026-07-20T08:00:00Z", dry_weather_flow_present=False
        )
        site = fx.setup_site_with_approved_plan(
            program["term_id"],
            esc_plan_reference="ESC-M",
            site_name="SITE-M",
            operator_name="Northgate Civil",
            disturbed_acres=1.50,
        )
        inspection = fx.create_esc_inspection(site["id"], "2026-07-01", "2026-07-31")
        fx.add_findings(inspection["id"], ["MINOR"])
        finalized = fx.finalize_inspection(inspection["id"])
        fx.assess_load(outfall_id, "FINAL", 2026)
        report = fx.create_report(program["term_id"], "2026-01-01", "2026-12-31")
        return {
            **program,
            "site": site,
            "inspection": finalized,
            "report": report,
        }

    @pytest.fixture
    def compiled(self, reported_program):
        """The one compile call whose frozen statistics every test below reads."""
        return fx.compile_report(
            reported_program["report"]["id"], reported_program["term_id"]
        )

    def test_07_the_index_caps_each_measure_at_a_hundred_and_divides_once(
        self, compiled
    ):
        """Weights 1, 3, 2, 2, 1 and 1 over an over-attaining measure give 88.50.

        PRD: "Each measure contributes its `weight` multiplied by its `attainment_pct`
        capped at 100.00 — over-attainment is clipped per measure precisely so that a
        runaway measure cannot mask a measure that is behind. Those contributions are
        summed, the `weight` values of the same measures are summed, and the index is the
        first sum divided by the second, rounded to 2 decimal places exactly once at the
        end; rounding each measure's contribution before the division drifts from the
        specified value."

        Design: Corner/calculations/annual_report_statistics_count_the_closed_window_and_round_the_index_once
        """
        assert compiled["compliance_index"] == pytest.approx(88.50, abs=0.01), (
            "75 plus 300 plus 160 plus 200 plus 100 plus 50 over a total weight of 10 "
            f"is 88.50, got {compiled['compliance_index']}"
        )

    def test_08_the_met_census_counts_three_of_the_six_measures(
        self, reported_program, compiled
    ):
        """The over-attaining measure is MET even though the index clipped it.

        PRD: "`measurable_goals_met_count` counts the term's `ACTIVE` control measures
        whose `goal_status` is `MET` at compile time." And: "If `attainment_pct` is at
        least 100.00, the result is `MET`."

        Design: Corner/calculations/annual_report_statistics_count_the_closed_window_and_round_the_index_once
        """
        assert compiled["measurable_goals_met_count"] == 3, (
            "illicit discharge, post construction and municipal operations are met, got "
            f"{compiled['measurable_goals_met_count']}"
        )

        post_construction = fx.read_measure(
            reported_program["measures"]["POST_CONSTRUCTION"]["id"]
        )
        assert post_construction["attainment_pct"] == pytest.approx(125.00, abs=0.01), (
            "ten of eight is 125.00 percent on the measure itself"
        )
        assert post_construction["goal_status"] == "MET", "over-attainment is still met"

    def test_09_the_screening_statistics_cover_the_one_active_outfall(self, compiled):
        """Two visits at one outfall are full coverage of one outfall.

        PRD: "`screenings_completed` counts the term's dry-weather screening observations
        whose `observed_at` lies in the window. `outfall_screening_coverage_pct` is 0.00
        when the term has no `ACTIVE` outfall; otherwise it is 100 multiplied by the
        number of distinct `ACTIVE` outfalls with at least one screening in the window,
        divided by the count of `ACTIVE` outfalls in the term, rounded to 2 decimal
        places."

        Design: Corner/calculations/annual_report_statistics_count_the_closed_window_and_round_the_index_once
        """
        assert compiled["screenings_completed"] == 2, (
            f"both July visits fall in the window, got {compiled['screenings_completed']}"
        )
        assert compiled["outfall_screening_coverage_pct"] == pytest.approx(
            100.00, abs=0.01
        ), (
            "one distinct screened outfall over one active outfall is 100.00, got "
            f"{compiled['outfall_screening_coverage_pct']}"
        )

    def test_10_the_case_and_inspection_counts_follow_their_own_definitions(
        self, compiled
    ):
        """One finalized erosion-control inspection, no cases, no facility work.

        PRD: "`cases_opened` counts illicit discharge cases whose `opened_at` lies in the
        window, and `cases_resolved` counts those whose `status` is `RESOLVED` and whose
        `resolved_at` lies in the window. `construction_inspections_finalized` counts
        `CONSTRUCTION_ESC` inspections with `status` `FINALIZED` and `finalized_at` in the
        window, and `facility_inspections_finalized` counts
        `POST_CONSTRUCTION_MAINTENANCE` inspections on the same basis."

        Design: Corner/calculations/annual_report_statistics_count_the_closed_window_and_round_the_index_once
        """
        assert compiled["cases_opened"] == 0, "every screening came back clear"
        assert compiled["cases_resolved"] == 0, "there was no case to resolve"
        assert compiled["construction_inspections_finalized"] == 1, (
            "the one finalized erosion-control inspection counts"
        )
        assert compiled["facility_inspections_finalized"] == 0, (
            "no maintenance inspection was ever finalized"
        )

    def test_11_a_minor_finding_generates_no_enforcement_to_count(
        self, reported_program, compiled
    ):
        """A score of eight is far below the automatic notice threshold.

        PRD: "`deficiency_score` is the resulting figure capped at 100, and
        `escalation_triggered` is set true exactly when `deficiency_score` is 70 or more."
        And: "`enforcement_actions_issued` counts enforcement actions whose `issued_at`
        lies in the window and whose `status` is `ISSUED`, `ESCALATED` or `CLOSED`, and
        `total_penalty_assessed_cents` sums `penalty_cents` over exactly that same set."

        Design: Corner/calculations/annual_report_statistics_count_the_closed_window_and_round_the_index_once
        """
        assert reported_program["inspection"]["deficiency_score"] == 8, (
            "one minor finding scores eight points"
        )
        assert reported_program["inspection"]["escalation_triggered"] is False, (
            "eight points trigger nothing"
        )
        assert compiled["enforcement_actions_issued"] == 0, (
            "no action was ever issued, automatically or by hand"
        )
        assert compiled["total_penalty_assessed_cents"] == 0, "the ledger is empty"

    def test_12_the_sweeping_and_load_totals_are_summed_over_the_window(self, compiled):
        """Twenty lane miles swept, and a net annual load of nothing.

        PRD: "`swept_lane_miles` sums `lane_miles_swept` over the sweeping runs whose
        `run_start_date` lies in the window, rounded to 2 decimal places.
        `net_annual_load_lb` sums `last_assessed_net_load_lb` over the `ACTIVE` outfalls
        whose `last_assessed_year` equals the calendar year of `reporting_period_end`,
        rounded to 2 decimal places."

        Design: Corner/calculations/annual_report_statistics_count_the_closed_window_and_round_the_index_once
        """
        assert compiled["swept_lane_miles"] == pytest.approx(20.00, abs=0.01), (
            f"the single August run is in the window, got {compiled['swept_lane_miles']}"
        )
        assert compiled["net_annual_load_lb"] == pytest.approx(0.00, abs=0.01), (
            "no sample was validated, so the assessed net load was 0.00, got "
            f"{compiled['net_annual_load_lb']}"
        )

    def test_13_a_single_behind_measure_leaves_certification_available(
        self, reported_program, compiled
    ):
        """AT_RISK is not the posture that blocks the end of the chain.

        PRD: "Otherwise, if `behind_measure_count` is exactly one, or
        `exceeding_outfall_count` is at least one, it becomes `AT_RISK`." And: "A
        `NON_COMPLIANT` posture blocks annual report certification, which is how a single
        behind measure eventually reaches the end of the cascade chain."

        Design: Corner/calculations/annual_report_statistics_count_the_closed_window_and_round_the_index_once
        """
        assert compiled["status"] == "COMPILED", "the report froze its statistics"
        assert compiled["compiled_by_user_id"] == MANAGER_ONE, "the compiler is recorded"

        term = fx.read_term(reported_program["term_id"])
        assert term["behind_measure_count"] == 1, (
            f"only monitoring is behind, got {term['behind_measure_count']}"
        )
        assert term["compliance_posture"] == "AT_RISK", (
            "one behind measure and no exceeding outfall is at risk"
        )

        certified = fx.certify_report(reported_program["report"]["id"])
        assert certified["status"] == "CERTIFIED", (
            "an at-risk posture does not block certification"
        )
