"""Two field calculations: the indicator panel and the street-sweeping credit."""

import pytest
from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import IDDE_HEADERS, MANAGER_HEADERS

OUTFALL_FIELDS = {
    "receiving_water": "Mill Creek",
    "drainage_area_acres": 45.00,
    "priority_tier": "HIGH",
    "baseline_concentration_mg_per_l": 0.45,
    "design_runoff_kl": 20000,
    "sweeping_capacity_lane_miles_per_month": 40.00,
}


def _screen(outfall_id, observed_at, **panel):
    """Record one dry-weather screening carrying the given indicator panel."""
    return validate_success(
        api_client.create_observation(
            outfall_id,
            factories.screening_payload(observed_at, **panel),
            IDDE_HEADERS,
        ),
        201,
    )


class TestTheIndicatorPanelCountsStrictExceedances:
    """Four outfalls so that four panels are judged independently of each other."""

    @pytest.fixture
    def four_outfalls(self):
        """An ACTIVE term carrying OF-01 through OF-04, all alike."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01", "OF-02", "OF-03", "OF-04"),
            funding_target_cents=25000,
            outfall_overrides=dict(OUTFALL_FIELDS),
        )
        return program

    def test_01_no_dry_weather_flow_short_circuits_past_every_indicator(
        self, four_outfalls
    ):
        """A dry pipe is CLEAR however alarming the readings are.

        PRD: "If `dry_weather_flow_present` is false, the result is `CLEAR` — no flow
        means no discharge, and no indicator is consulted."

        Design: Corner/calculations/dry_weather_screening_counts_strict_exceedances_and_honours_the_hard_trigger
        """
        outfall = four_outfalls["outfalls"]["OF-01"]

        observation = _screen(
            outfall["id"],
            "2026-08-01T08:00:00Z",
            dry_weather_flow_present=False,
            indicator_bacteria_mpn=90000.0,
            indicator_surfactant_mg_per_l=4.00,
            indicator_ammonia_mg_per_l=9.00,
        )

        assert observation["screening_result"] == "CLEAR", (
            "no flow decides the result before any limit is consulted"
        )

        stored = fx.read_outfall(outfall["id"])
        assert stored["screening_status"] == "CLEAR", "the outfall reads clear"
        assert stored["open_case_count"] == 0, "no case was opened"

    def test_02_readings_sitting_exactly_on_the_limits_are_not_exceedances(
        self, four_outfalls
    ):
        """1000, 0.25 and 0.50 are all one step short of an exceedance.

        PRD: "Otherwise the server counts how many of three indicator limits are
        exceeded, in each case by a strictly greater comparison, treating a null reading
        as not exceeding: `indicator_bacteria_mpn` above 1000 most probable number per
        100 millilitres, `indicator_surfactant_mg_per_l` above 0.25 milligrams per litre,
        and `indicator_ammonia_mg_per_l` above 0.50 milligrams per litre." And: "Because
        each comparison is strict, a reading sitting exactly on a limit is not an
        exceedance."

        Design: Corner/calculations/dry_weather_screening_counts_strict_exceedances_and_honours_the_hard_trigger
        """
        outfall = four_outfalls["outfalls"]["OF-02"]

        observation = _screen(
            outfall["id"],
            "2026-08-01T09:00:00Z",
            dry_weather_flow_present=True,
            indicator_bacteria_mpn=1000.0,
            indicator_surfactant_mg_per_l=0.25,
            indicator_ammonia_mg_per_l=0.50,
        )

        assert observation["screening_result"] == "CLEAR", (
            "three readings on their limits exceed nothing"
        )

        stored = fx.read_outfall(outfall["id"])
        assert stored["screening_status"] == "CLEAR", "the outfall reads clear"
        assert stored["open_case_count"] == 0, "no case was opened"

    def test_03_two_exceedances_make_the_visit_suspect(self, four_outfalls):
        """Bacteria and surfactant a hair over the line are enough together.

        PRD: "If two or more of those three are exceeded, the result is `SUSPECT`."

        Design: Corner/calculations/dry_weather_screening_counts_strict_exceedances_and_honours_the_hard_trigger
        """
        outfall = four_outfalls["outfalls"]["OF-03"]

        observation = _screen(
            outfall["id"],
            "2026-08-01T10:00:00Z",
            dry_weather_flow_present=True,
            indicator_bacteria_mpn=1001.0,
            indicator_surfactant_mg_per_l=0.26,
            indicator_ammonia_mg_per_l=0.50,
        )

        assert observation["screening_result"] == "SUSPECT", (
            "two exceedances decide the result while ammonia on its limit adds nothing"
        )

        stored = fx.read_outfall(outfall["id"])
        assert stored["screening_status"] == "SUSPECT", "the outfall turns suspect"
        assert stored["open_case_count"] == 1, "the cascade opened one case"
        assert stored["screening_count"] == 1, "one visit is on the record"

    def test_04_a_single_overwhelming_surfactant_reading_stands_alone(
        self, four_outfalls
    ):
        """One exceedance is normally not enough, but this one is.

        PRD: "Otherwise a single overwhelming detergent reading is enough on its own: if
        `indicator_surfactant_mg_per_l` is above 1.00 milligrams per litre, the result is
        `SUSPECT`."

        Design: Corner/calculations/dry_weather_screening_counts_strict_exceedances_and_honours_the_hard_trigger
        """
        outfall = four_outfalls["outfalls"]["OF-04"]

        observation = _screen(
            outfall["id"],
            "2026-08-01T11:00:00Z",
            dry_weather_flow_present=True,
            indicator_bacteria_mpn=500.0,
            indicator_surfactant_mg_per_l=1.01,
            indicator_ammonia_mg_per_l=0.10,
        )

        assert observation["screening_result"] == "SUSPECT", (
            "the hard trigger fires on a single exceedance"
        )

        stored = fx.read_outfall(outfall["id"])
        assert stored["screening_status"] == "SUSPECT", "the outfall turns suspect"
        assert stored["open_case_count"] == 1, "the cascade opened one case"
        assert stored["screening_count"] == 1, "one visit is on the record"

    def test_05_one_case_per_suspect_visit_and_no_gate_yet(self, four_outfalls):
        """Two suspect panels out of four make two cases and no BEHIND gate.

        PRD: "A `SUSPECT` result moves `screening_status` from either `NOT_SCREENED` or
        `CLEAR` to `SUSPECT` and additionally opens a case: the server creates an
        **illicit discharge case** in `OPEN` whose `outfall_id` is this outfall and whose
        `origin_observation_id` is the new observation" And: "For the `ILLICIT_DISCHARGE`
        measure, if `open_case_count` is greater than three, the result is `BEHIND`."

        Design: Corner/calculations/dry_weather_screening_counts_strict_exceedances_and_honours_the_hard_trigger
        """
        outfalls = four_outfalls["outfalls"]
        _screen(
            outfalls["OF-01"]["id"],
            "2026-08-01T08:00:00Z",
            dry_weather_flow_present=False,
            indicator_bacteria_mpn=90000.0,
            indicator_surfactant_mg_per_l=4.00,
            indicator_ammonia_mg_per_l=9.00,
        )
        _screen(
            outfalls["OF-02"]["id"],
            "2026-08-01T09:00:00Z",
            dry_weather_flow_present=True,
            indicator_bacteria_mpn=1000.0,
            indicator_surfactant_mg_per_l=0.25,
            indicator_ammonia_mg_per_l=0.50,
        )
        third = _screen(
            outfalls["OF-03"]["id"],
            "2026-08-01T10:00:00Z",
            dry_weather_flow_present=True,
            indicator_bacteria_mpn=1001.0,
            indicator_surfactant_mg_per_l=0.26,
            indicator_ammonia_mg_per_l=0.50,
        )
        fourth = _screen(
            outfalls["OF-04"]["id"],
            "2026-08-01T11:00:00Z",
            dry_weather_flow_present=True,
            indicator_bacteria_mpn=500.0,
            indicator_surfactant_mg_per_l=1.01,
            indicator_ammonia_mg_per_l=0.10,
        )

        cases, meta = validate_paginated(
            api_client.list_illicit_discharge_cases(MANAGER_HEADERS)
        )
        assert meta["total_count"] == 2, (
            f"only the two suspect visits opened cases, got {meta['total_count']}"
        )
        origins = {case["origin_observation_id"] for case in cases}
        assert origins == {third["id"], fourth["id"]}, (
            "each case names the suspect screening it came from"
        )
        assert all(case["status"] == "OPEN" for case in cases), "both cases open"

        measure = fx.read_measure(four_outfalls["measures"]["ILLICIT_DISCHARGE"]["id"])
        assert measure["open_case_count"] == 2, (
            f"the measure counts both open cases, got {measure['open_case_count']}"
        )
        assert measure["goal_status"] != "BEHIND", (
            "two open cases do not exceed the gate's threshold of three"
        )


class TestSweepingCreditIsTheLesserOfEarnedAndCap:
    """The same gross load, two lane-mile totals, and one binding quarter-cap."""

    @pytest.fixture
    def swept_program(self):
        """OF-01 and OF-02, each with one validated sample, swept 20 and 5 lane miles."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01", "OF-02"),
            funding_target_cents=25000,
            outfall_overrides=dict(OUTFALL_FIELDS),
        )
        first = program["outfalls"]["OF-01"]
        second = program["outfalls"]["OF-02"]
        fx.record_validated_sample(first["id"], "2026-06-10T09:00:00Z", 0.45, 40000.00)
        fx.record_validated_sample(second["id"], "2026-06-10T09:00:00Z", 0.45, 40000.00)
        fx.append_sweeping_run(first["id"], "2026-08-01", "2026-08-10", 20.00)
        fx.append_sweeping_run(first["id"], "2025-12-01", "2025-12-10", 30.00)
        fx.append_sweeping_run(second["id"], "2026-08-01", "2026-08-10", 5.00)
        return program

    def test_06_the_quarter_cap_binds_when_the_lane_miles_earn_more(self, swept_program):
        """Seventeen earned pounds are clipped to a quarter of the gross load.

        PRD: "Earned credit is the lane miles swept in the reporting year — the sum of
        `lane_miles_swept` over the outfall's runs whose `run_start_date` falls in that
        year — multiplied by 0.85 pounds of load reduction per lane mile, rounded to 2
        decimal places. That earned figure is capped at one quarter of the variant's own
        `gross_load_lb`, itself rounded to 2 decimal places, and `sweeping_credit_lb` is
        the smaller of earned and cap." And: "`net_load_lb` is `gross_load_lb` minus
        `sweeping_credit_lb`, rounded to 2 decimal places."

        Design: Corner/calculations/sweeping_credit_is_the_lesser_of_earned_pounds_and_a_quarter_of_the_gross_load
        """
        assessment = fx.assess_load(
            swept_program["outfalls"]["OF-01"]["id"], "FINAL", 2026
        )

        assert assessment["gross_load_lb"] == pytest.approx(39.68, abs=0.01), (
            f"one sample of 39.6832 pounds rounds to 39.68, got {assessment['gross_load_lb']}"
        )
        assert assessment["sweeping_credit_lb"] == pytest.approx(9.92, abs=0.01), (
            "the earned 17.00 is clipped to the quarter-cap of 9.92, got "
            f"{assessment['sweeping_credit_lb']}"
        )
        assert assessment["net_load_lb"] == pytest.approx(29.76, abs=0.01), (
            f"39.68 less 9.92 is 29.76, got {assessment['net_load_lb']}"
        )

    def test_07_a_final_variant_counts_only_the_samples_in_hand(self, swept_program):
        """No projected shortfall is priced into the final reckoning.

        PRD: "In the `FINAL` variant the projected shortfall is treated as zero, so only
        validated samples count."

        Design: Corner/calculations/sweeping_credit_is_the_lesser_of_earned_pounds_and_a_quarter_of_the_gross_load
        """
        assessment = fx.assess_load(
            swept_program["outfalls"]["OF-01"]["id"], "FINAL", 2026
        )

        assert assessment["validated_sample_count"] == 1, "one sample was adjudicated"
        assert assessment["projected_sample_count"] == 0, (
            "the final variant projects nothing"
        )
        assert assessment["variant"] == "FINAL", "the variant is echoed back"
        assert assessment["reporting_year"] == 2026, "the year is echoed back"

    def test_08_the_earning_year_filters_the_runs_the_log_still_remembers(
        self, swept_program
    ):
        """Fifty lane miles are logged; only twenty of them earn in 2026.

        PRD: "Each accepted run is appended to the outfall's append-only `sweeping_runs`
        list as an entry holding `run_start_date`, `run_end_date` and `lane_miles_swept`,
        and raises the outfall's `swept_lane_miles_ytd`, which is the sum of
        `lane_miles_swept` over the whole list to 2 decimal places." And: "Earned credit
        is the lane miles swept in the reporting year — the sum of `lane_miles_swept`
        over the outfall's runs whose `run_start_date` falls in that year — multiplied by
        0.85 pounds of load reduction per lane mile, rounded to 2 decimal places."

        Design: Corner/calculations/sweeping_credit_is_the_lesser_of_earned_pounds_and_a_quarter_of_the_gross_load
        """
        first = swept_program["outfalls"]["OF-01"]

        stored = fx.read_outfall(first["id"])
        assert stored["swept_lane_miles_ytd"] == pytest.approx(50.00, abs=0.01), (
            "the log keeps both runs, got "
            f"{stored['swept_lane_miles_ytd']}"
        )
        assert len(stored["sweeping_runs"]) == 2, "two entries were appended"

        assessment = fx.assess_load(first["id"], "FINAL", 2026)
        assert assessment["sweeping_credit_lb"] == pytest.approx(9.92, abs=0.01), (
            "the 2025 run earns nothing in 2026, and the cap binds regardless"
        )

    def test_09_earned_credit_passes_through_below_the_cap(self, swept_program):
        """Five lane miles earn 4.25 pounds, comfortably under the same cap.

        PRD: "That earned figure is capped at one quarter of the variant's own
        `gross_load_lb`, itself rounded to 2 decimal places, and `sweeping_credit_lb` is
        the smaller of earned and cap."

        Design: Corner/calculations/sweeping_credit_is_the_lesser_of_earned_pounds_and_a_quarter_of_the_gross_load
        """
        assessment = fx.assess_load(
            swept_program["outfalls"]["OF-02"]["id"], "FINAL", 2026
        )

        assert assessment["gross_load_lb"] == pytest.approx(39.68, abs=0.01), (
            "the same single sample gives the same gross load"
        )
        assert assessment["sweeping_credit_lb"] == pytest.approx(4.25, abs=0.01), (
            "five lane miles at 0.85 earn 4.25, below the 9.92 cap, got "
            f"{assessment['sweeping_credit_lb']}"
        )
        assert assessment["net_load_lb"] == pytest.approx(35.43, abs=0.01), (
            f"39.68 less 4.25 is 35.43, got {assessment['net_load_lb']}"
        )

    def test_10_a_final_assessment_persists_its_figures_and_leaves_tmdl_unassessed(
        self, swept_program
    ):
        """No allocation applies, so the status is not an exceedance verdict.

        PRD: "When the term's `tmdl_applicable` is false the status is `NOT_ASSESSED`."
        And: "A `FINAL` assessment writes `tmdl_status`,
        `last_assessed_gross_load_lb`, `last_assessed_credit_lb`,
        `last_assessed_net_load_lb` and `last_assessed_year` onto the outfall, then
        recomputes the term's `exceeding_outfall_count` and `compliance_posture`"

        Design: Corner/calculations/sweeping_credit_is_the_lesser_of_earned_pounds_and_a_quarter_of_the_gross_load
        """
        expected = {"OF-01": (9.92, 29.76), "OF-02": (4.25, 35.43)}
        for code, (credit, net) in expected.items():
            outfall_id = swept_program["outfalls"][code]["id"]
            assessment = fx.assess_load(outfall_id, "FINAL", 2026)
            assert assessment["tmdl_status"] == "NOT_ASSESSED", (
                f"{code} carries no allocation to compare against"
            )

            stored = fx.read_outfall(outfall_id)
            assert stored["tmdl_status"] == "NOT_ASSESSED", f"{code} persisted the status"
            assert stored["last_assessed_year"] == 2026, f"{code} persisted the year"
            assert stored["last_assessed_gross_load_lb"] == pytest.approx(
                39.68, abs=0.01
            ), f"{code} persisted the gross load"
            assert stored["last_assessed_credit_lb"] == pytest.approx(credit, abs=0.01), (
                f"{code} persisted its own credit"
            )
            assert stored["last_assessed_net_load_lb"] == pytest.approx(net, abs=0.01), (
                f"{code} persisted its own net load"
            )

        term = fx.read_term(swept_program["term_id"])
        assert term["exceeding_outfall_count"] == 0, (
            "an unassessed status is not an exceedance"
        )
