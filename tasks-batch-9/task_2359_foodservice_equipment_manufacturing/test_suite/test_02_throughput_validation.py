"""Cooking-performance validation: the two throughput figures, the gates and the retest loop."""

import pytest

from test_helpers import (
    ApiErrorId,
    add_test_runs,
    conclude_validation,
    create_chain_account,
    create_chain_configuration,
    create_equipment_model,
    open_performance_validation,
    read_performance_validation,
    retest_validation,
    set_clock,
    validate_error,
    validate_success,
)


def _draft_configuration(**model_overrides):
    """A DRAFT configuration on an unlisted model: enough to open a validation."""
    set_clock()
    model = create_equipment_model(
        supported_controls_packages=["STANDARD_DIAL"], **model_overrides
    )
    account = create_chain_account()
    config = create_chain_configuration(
        account["id"],
        model["id"],
        account["version"],
        option_codes=[],
        controls_package="STANDARD_DIAL",
        branding_kit="NONE",
    )
    return config


class TestCertifiedVersusAsTestedThroughput:
    def test_certified_best_window_passes_a_target_the_pooled_series_would_fail(self):
        """Four runs certify 66.06 while the pooled series reads 63.22, and only 66.06 gates.

        PRD §3.4: "The **certified** figure — the one that gates approval — is the best
        three-run window: for every group of three consecutive runs, take the total
        `units_produced` across those three runs, multiply by sixty, divide by the total
        `minutes` across those same three runs, and keep the largest such rate across
        all windows; round that maximum half up to two decimal places, and round only
        that final maximum, never the individual window rates."

        Design: Difficulty/dual_variant_calc/throughput_certified_best_window_versus_as_tested_full_series
        """
        config = _draft_configuration()
        validation = open_performance_validation(
            config["id"],
            config["version"],
            target_throughput_units_per_hour=65.0,
            hold_temp_target_c=175.0,
        )
        add_test_runs(
            validation["id"],
            [(95, 90, 175.0), (108, 95, 174.0), (102, 92, 176.0), (88, 96, 175.5)],
        )

        concluded = conclude_validation(validation["id"])

        assert concluded["certified_throughput_units_per_hour"] == pytest.approx(
            66.06, abs=0.01
        ), (
            "the best three-run window is runs 1 to 3, 305 units in 277 minutes, which "
            f"is 66.06 units per hour, got "
            f"{concluded['certified_throughput_units_per_hour']}"
        )
        assert concluded["as_tested_throughput_units_per_hour"] == pytest.approx(
            63.22, abs=0.01
        ), (
            "the as-tested figure pools all four runs, 393 units in 373 minutes, which "
            f"is 63.22 units per hour, got "
            f"{concluded['as_tested_throughput_units_per_hour']}"
        )
        assert concluded["status"] == "PASSED", (
            "the certified 66.06 clears the 65.0 target even though the pooled 63.22 "
            f"would not, so the validation passes, got {concluded['status']}"
        )
        assert concluded["attempt_count"] == 1, (
            f"the conclusion increments attempt_count to 1, got {concluded['attempt_count']}"
        )
        assert concluded["failure_reason"] is None, (
            f"a passing validation records no failure reason, got {concluded['failure_reason']}"
        )

    def test_certified_figure_is_the_maximum_window_even_when_the_weak_run_comes_first(
        self,
    ):
        """Leading the series with the weakest run leaves the certified figure at 66.06.

        PRD §3.4: "The **as-tested** figure pools the whole series instead: total
        `units_produced` across every run multiplied by sixty, divided by total
        `minutes` across every run, rounded half up to two decimal places, and stored in
        `as_tested_throughput_units_per_hour`. The as-tested number is what the chain is
        shown, and because weak runs drag it down it is normally the lower of the two;
        it is never used as the pass/fail gate."

        Design: Difficulty/dual_variant_calc/throughput_certified_best_window_versus_as_tested_full_series
        """
        config = _draft_configuration()
        validation = open_performance_validation(
            config["id"],
            config["version"],
            target_throughput_units_per_hour=65.0,
            hold_temp_target_c=175.0,
        )
        add_test_runs(
            validation["id"],
            [(88, 96, 175.5), (95, 90, 175.0), (108, 95, 174.0), (102, 92, 176.0)],
        )

        concluded = conclude_validation(validation["id"])

        assert concluded["certified_throughput_units_per_hour"] == pytest.approx(
            66.06, abs=0.01
        ), (
            "the second window, runs 2 to 4, is the best at 305 units in 277 minutes, "
            f"which is 66.06 units per hour, got "
            f"{concluded['certified_throughput_units_per_hour']}"
        )
        assert concluded["as_tested_throughput_units_per_hour"] == pytest.approx(
            63.22, abs=0.01
        ), (
            "the pooled figure is order-independent at 393 units in 373 minutes, which "
            f"is 63.22 units per hour, got "
            f"{concluded['as_tested_throughput_units_per_hour']}"
        )
        assert concluded["status"] == "PASSED", (
            "the gate reads the certified window figure, not the pooled one, so a 65.0 "
            f"target passes, got {concluded['status']}"
        )
        assert len(concluded["test_runs"]) == 4, (
            f"all four runs stay on the row, got {len(concluded['test_runs'])}"
        )


class TestHoldTemperatureTolerance:
    def test_a_run_at_exactly_two_degrees_of_deviation_passes_after_a_failing_attempt(
        self,
    ):
        """177.1 C fails the 175.0 target while exactly 177.0 C passes it.

        PRD §3.4: "The hold-temperature gate passes when every run's `hold_temp_c`
        differs from `hold_temp_target_c` by no more than two degrees Celsius in
        absolute terms, so a target of 74 degrees admits measurements from 72 through 76
        inclusive."

        Design: Difficulty/boundary_precision_check/hold_temp_deviation_exactly_at_tolerance_still_passes_validation
        """
        config = _draft_configuration()
        validation = open_performance_validation(
            config["id"],
            config["version"],
            target_throughput_units_per_hour=60.0,
            hold_temp_target_c=175.0,
        )
        add_test_runs(
            validation["id"], [(95, 90, 177.1), (108, 95, 174.0), (102, 92, 175.0)]
        )

        first = conclude_validation(validation["id"])

        assert first["status"] == "FAILED", (
            "a deviation of 2.1 C exceeds the tolerance, so the attempt fails, got "
            f"{first['status']}"
        )
        assert first["failure_reason"] == "HOLD_TEMP_OUT_OF_TOLERANCE", (
            "throughput was above target, so the recorded reason must be the hold "
            f"temperature one, got {first['failure_reason']}"
        )
        assert first["certified_throughput_units_per_hour"] == pytest.approx(
            66.06, abs=0.01
        ), (
            "both figures are stamped regardless of the outcome, so the certified rate "
            f"is 66.06, got {first['certified_throughput_units_per_hour']}"
        )

        reopened = retest_validation(validation["id"])
        assert reopened["status"] == "IN_PROGRESS", (
            f"retesting takes a FAILED validation back to IN_PROGRESS, got {reopened['status']}"
        )

        add_test_runs(
            validation["id"], [(95, 90, 177.0), (108, 95, 173.0), (102, 92, 175.0)]
        )
        second = conclude_validation(validation["id"])

        assert second["status"] == "PASSED", (
            "deviations of exactly 2.0 C in both directions are inside the tolerance, "
            f"so the second attempt passes, got {second['status']}"
        )
        assert second["certified_throughput_units_per_hour"] == pytest.approx(
            66.06, abs=0.01
        ), (
            f"the second series certifies 66.06, got "
            f"{second['certified_throughput_units_per_hour']}"
        )
        assert second["as_tested_throughput_units_per_hour"] == pytest.approx(
            66.06, abs=0.01
        ), (
            "a three-run series pools to the same rate as its only window, got "
            f"{second['as_tested_throughput_units_per_hour']}"
        )
        assert second["failure_reason"] is None, (
            f"the passing conclusion clears the failure reason, got {second['failure_reason']}"
        )
        assert second["attempt_count"] == 2, (
            "the retest does not clear attempt_count, so the second conclusion leaves "
            f"it at 2, got {second['attempt_count']}"
        )

    @pytest.mark.parametrize(
        "measured_temp,expected_status,expected_reason",
        [
            (177.0, "PASSED", None),
            (177.1, "FAILED", "HOLD_TEMP_OUT_OF_TOLERANCE"),
            (173.0, "PASSED", None),
            (172.9, "FAILED", "HOLD_TEMP_OUT_OF_TOLERANCE"),
        ],
    )
    def test_the_tolerance_band_is_inclusive_at_two_degrees_in_both_directions(
        self, measured_temp, expected_status, expected_reason
    ):
        """Deviations of exactly 2.0 C pass and 2.1 C fails, with throughput held above target.

        PRD §3.4: "When either fails, it moves `IN_PROGRESS → FAILED` and
        `failure_reason` is set to `THROUGHPUT_BELOW_TARGET` if the throughput gate was
        the one that failed, and otherwise to `HOLD_TEMP_OUT_OF_TOLERANCE` — so a run
        series that fails both gates records the throughput reason."

        Design: Difficulty/boundary_precision_check/hold_temp_deviation_exactly_at_tolerance_still_passes_validation
        """
        config = _draft_configuration()
        validation = open_performance_validation(
            config["id"],
            config["version"],
            target_throughput_units_per_hour=60.0,
            hold_temp_target_c=175.0,
        )
        add_test_runs(
            validation["id"],
            [(95, 90, measured_temp), (108, 95, 175.0), (102, 92, 175.0)],
        )

        concluded = conclude_validation(validation["id"])

        assert concluded["certified_throughput_units_per_hour"] == pytest.approx(
            66.06, abs=0.01
        ), (
            "the throughput gate is comfortably clear in every case at 66.06 against a "
            f"60.0 target, got {concluded['certified_throughput_units_per_hour']}"
        )
        assert concluded["status"] == expected_status, (
            f"a measurement of {measured_temp} C against a 175.0 C target must leave "
            f"the validation {expected_status}, got {concluded['status']}"
        )
        assert concluded["failure_reason"] == expected_reason, (
            f"a measurement of {measured_temp} C must record a failure reason of "
            f"{expected_reason}, got {concluded['failure_reason']}"
        )


class TestConclusionGates:
    def test_conclusion_needs_three_runs_and_is_not_replayable_once_passed(
        self, api, application_engineer
    ):
        """Two runs are refused without spending an attempt, and a PASSED row cannot re-conclude.

        PRD §3.4: "Concluding requires at least three runs on the validation — fewer is
        rejected with `ERR_MIN_TEST_RUNS_NOT_MET` — and an `attempt_count` still below
        three, the retest ceiling; a fourth attempt is rejected with
        `ERR_RETEST_LIMIT_EXCEEDED`."

        Design: Corner/validations/conclusion_needs_three_runs_and_is_not_replayable_once_passed
        """
        config = _draft_configuration()
        validation = open_performance_validation(
            config["id"],
            config["version"],
            target_throughput_units_per_hour=60,
            hold_temp_target_c=175.0,
        )
        assert validation["status"] == "IN_PROGRESS", (
            f"a new validation opens IN_PROGRESS, got {validation['status']}"
        )
        assert validation["attempt_count"] == 0, (
            f"a new validation starts with attempt_count 0, got {validation['attempt_count']}"
        )
        add_test_runs(validation["id"], [(95, 90, 175.0), (108, 95, 175.0)])

        too_few = api.conclude_performance_validation(
            validation["id"], {}, application_engineer
        )
        validate_error(too_few, ApiErrorId.ERR_MIN_TEST_RUNS_NOT_MET.value)
        assert read_performance_validation(validation["id"])["attempt_count"] == 0, (
            "a refused conclusion must not spend an attempt"
        )

        add_test_runs(validation["id"], [(102, 92, 176.0)])
        concluded = validate_success(
            api.conclude_performance_validation(validation["id"], {}, application_engineer)
        )
        assert concluded["status"] == "PASSED", (
            f"the third run makes the same conclusion succeed, got {concluded['status']}"
        )
        assert concluded["certified_throughput_units_per_hour"] == pytest.approx(
            66.06, abs=0.01
        ), (
            f"the single window certifies 66.06, got "
            f"{concluded['certified_throughput_units_per_hour']}"
        )
        assert concluded["attempt_count"] == 1, (
            f"the successful conclusion spends one attempt, got {concluded['attempt_count']}"
        )

        replay = api.conclude_performance_validation(
            validation["id"], {}, application_engineer
        )
        validate_error(replay, ApiErrorId.ERR_VALIDATION_STATE_INVALID.value)
        assert read_performance_validation(validation["id"])["attempt_count"] == 1, (
            "PASSED is terminal, so the replay must not stamp a second attempt"
        )

    def test_retest_loop_is_capped_at_three_attempts(self, api, application_engineer):
        """Three failing conclusions exhaust the attempt budget and the fourth retest is refused.

        PRD §3.4: "Retesting takes it `FAILED → IN_PROGRESS`, is permitted only while
        `attempt_count` is still below three and only while the parent configuration is
        in `DRAFT` or `REVISION_REQUESTED`, and wipes the slate: `test_runs` is cleared
        back to an empty array and `certified_throughput_units_per_hour`,
        `as_tested_throughput_units_per_hour` and `failure_reason` are all cleared to
        null. `attempt_count` is deliberately **not** cleared, which is what makes the
        retest loop finite."

        Design: Corner/validations/retest_loop_is_capped_at_three_attempts
        """
        config = _draft_configuration()
        validation = open_performance_validation(
            config["id"],
            config["version"],
            target_throughput_units_per_hour=60,
            hold_temp_target_c=175.0,
        )
        failing_series = [(40, 60, 175.0), (40, 60, 175.0), (40, 60, 175.0)]

        add_test_runs(validation["id"], failing_series)
        first = conclude_validation(validation["id"])
        assert first["status"] == "FAILED", (
            f"40.00 units per hour is below the 60 target, got {first['status']}"
        )
        assert first["certified_throughput_units_per_hour"] == pytest.approx(
            40.00, abs=0.01
        ), (
            "120 units in 180 minutes is 40.00 units per hour, got "
            f"{first['certified_throughput_units_per_hour']}"
        )
        assert first["failure_reason"] == "THROUGHPUT_BELOW_TARGET", (
            "every hold temperature was on target, so the throughput reason is "
            f"recorded, got {first['failure_reason']}"
        )
        assert first["attempt_count"] == 1, (
            f"the first conclusion spends one attempt, got {first['attempt_count']}"
        )

        reopened = retest_validation(validation["id"])
        assert reopened["status"] == "IN_PROGRESS", (
            f"the retest reopens the validation, got {reopened['status']}"
        )
        assert reopened["test_runs"] == [], (
            f"the retest wipes the run series, got {reopened['test_runs']}"
        )
        assert reopened["certified_throughput_units_per_hour"] is None, (
            "the retest clears the certified figure, got "
            f"{reopened['certified_throughput_units_per_hour']}"
        )
        assert reopened["as_tested_throughput_units_per_hour"] is None, (
            "the retest clears the as-tested figure, got "
            f"{reopened['as_tested_throughput_units_per_hour']}"
        )
        assert reopened["failure_reason"] is None, (
            f"the retest clears the failure reason, got {reopened['failure_reason']}"
        )
        assert reopened["attempt_count"] == 1, (
            "the retest deliberately does not clear attempt_count, got "
            f"{reopened['attempt_count']}"
        )

        add_test_runs(validation["id"], failing_series)
        second = conclude_validation(validation["id"])
        assert second["attempt_count"] == 2, (
            f"the second conclusion leaves attempt_count at 2, got {second['attempt_count']}"
        )

        retest_validation(validation["id"])
        add_test_runs(validation["id"], failing_series)
        third = conclude_validation(validation["id"])
        assert third["status"] == "FAILED", (
            f"the third attempt fails on throughput as well, got {third['status']}"
        )
        assert third["attempt_count"] == 3, (
            f"the third conclusion exhausts the budget at 3, got {third['attempt_count']}"
        )

        refused = api.retest_performance_validation(
            validation["id"], {}, application_engineer
        )
        validate_error(refused, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED.value)

        final = read_performance_validation(validation["id"])
        assert final["status"] == "FAILED", (
            f"the refused retest leaves the validation FAILED, got {final['status']}"
        )
        assert final["failure_reason"] == "THROUGHPUT_BELOW_TARGET", (
            f"the failure reason survives the refusal, got {final['failure_reason']}"
        )
