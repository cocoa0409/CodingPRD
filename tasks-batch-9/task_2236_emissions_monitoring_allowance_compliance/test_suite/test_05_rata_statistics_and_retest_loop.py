"""Relative accuracy statistics: the two permitted denominators, the boundary
at the pass threshold, and the retest cycle on one audit row."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_rata_test,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import rata_test_payload

RUN_SET_A = fx.RATA_RUNS_PASSING
RUN_SET_B = fx.RATA_RUNS_FAILING


def _read_test(rata_test_id):
    return validate_success(api_client.get_rata_test(rata_test_id, fx.QA))


class TestDualAccuracyDenominators:
    """The denominator swap can flip the verdict on identical runs."""

    def _low_emitter_audit(self):
        station = fx.setup_scheduled_rata_test(
            parameter="NOX_RATE",
            span_value=0.800,
            online=True,
            applicable_standard_value=0.500,
        )
        fx.record_rata_runs(station["rata_test"]["id"], RUN_SET_B)
        return station

    def test_the_reference_mean_denominator_fails_the_audit(self):
        """Divided by the measured 0.2700, the accuracy is 10.7 percent.

        PRD: "Under `REFERENCE_MEAN` — always permitted, and the value a
        scheduled audit carries by default — the denominator is `reference_mean`,
        the measured reference method mean of this very run set."

        Design: Difficulty/dual_variant_calc/dual_variant_rata_reference_mean_vs_applicable_standard_flips_verdict
        """
        station = self._low_emitter_audit()

        evaluated = fx.evaluate_rata_test(
            station["rata_test"]["id"], ra_basis="REFERENCE_MEAN"
        )
        assert_rata_test(evaluated)
        assert evaluated["reference_mean"] == 0.2700
        assert evaluated["cems_mean"] == 0.2456
        assert evaluated["mean_difference"] == 0.0244
        assert evaluated["confidence_coefficient"] == 0.0046
        assert evaluated["relative_accuracy_pct"] == 10.7, (
            "(0.0244 + 0.0046) / 0.2700 * 100 is 10.7, got "
            f"{evaluated['relative_accuracy_pct']}"
        )
        assert evaluated["status"] == "FAILED", (
            "10.7 is strictly above the 10.0 pass threshold"
        )
        assert evaluated["bias_test_failed"] is True
        assert evaluated["bias_adjustment_factor"] == 1.0993

    def test_the_applicable_standard_denominator_passes_the_identical_runs(self):
        """Divided by the 0.500 standard, the same runs give 5.8 percent.

        PRD: "Because the applicable standard is larger than a low emitter's
        measured reference mean, this basis always yields a *smaller* relative
        accuracy and can convert a failing audit into a passing one on identical
        runs."

        Design: Difficulty/dual_variant_calc/dual_variant_rata_reference_mean_vs_applicable_standard_flips_verdict
        """
        station = self._low_emitter_audit()
        rata_test_id = station["rata_test"]["id"]

        fx.evaluate_rata_test(rata_test_id, ra_basis="REFERENCE_MEAN")
        validate_success(
            api_client.reschedule_rata_test(
                rata_test_id,
                {
                    "window_start_utc": "2026-04-05T00:00:00Z",
                    "window_end_utc": "2026-04-06T00:00:00Z",
                },
                fx.QA,
            )
        )
        fx.record_rata_runs(rata_test_id, RUN_SET_B)

        reevaluated = fx.evaluate_rata_test(
            rata_test_id, ra_basis="APPLICABLE_STANDARD"
        )
        assert reevaluated["ra_basis"] == "APPLICABLE_STANDARD"
        assert reevaluated["mean_difference"] == 0.0244, (
            "the run statistics are unchanged; only the denominator moved"
        )
        assert reevaluated["relative_accuracy_pct"] == 5.8, (
            "(0.0244 + 0.0046) / 0.500 * 100 is 5.8, got "
            f"{reevaluated['relative_accuracy_pct']}"
        )
        assert reevaluated["status"] == "PASSED"


class TestRetestCycle:
    """`FAILED` is not terminal; `PASSED` is."""

    def _failed_audit(self):
        station = fx.setup_scheduled_rata_test(
            parameter="NOX_RATE",
            span_value=0.800,
            online=True,
            applicable_standard_value=0.500,
        )
        rata_test_id = station["rata_test"]["id"]
        recorded = fx.record_rata_runs(rata_test_id, RUN_SET_B)
        assert recorded["status"] == "RUNS_RECORDED"
        assert recorded["run_count"] == 9
        station["failed"] = fx.evaluate_rata_test(rata_test_id)
        return station

    def test_rescheduling_a_failed_audit_partially_resets_the_same_row(self):
        """attempt_number rises to 2 while the applicable standard survives.

        PRD: "It clears `runs`, resets `run_count` to 0, nulls `reference_mean`,
        `cems_mean`, `mean_difference`, `confidence_coefficient` and
        `relative_accuracy_pct`, sets `bias_test_failed` back to false and
        `bias_adjustment_factor` back to 1.0, returns `ra_basis` to
        `REFERENCE_MEAN`, raises `attempt_number` by one, sets `status` to
        `SCHEDULED`, and increments the audit's `version`."

        Design: Difficulty/non_linear_state_machine/non_linear_rata_test_cycles_back_to_scheduled_and_bumps_attempt_number
        """
        station = self._failed_audit()
        assert station["failed"]["relative_accuracy_pct"] == 10.7
        assert station["failed"]["status"] == "FAILED"

        system = validate_success(
            api_client.get_monitoring_system(station["system"]["id"], fx.QA)
        )
        assert system["qa_status"] == "RECERTIFICATION_PENDING", (
            "the system was never certified, so no demotion applies"
        )

        rescheduled = validate_success(
            api_client.reschedule_rata_test(
                station["rata_test"]["id"],
                {
                    "window_start_utc": "2026-04-06T00:00:00Z",
                    "window_end_utc": "2026-04-07T00:00:00Z",
                },
                fx.QA,
            )
        )
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["attempt_number"] == 2
        assert rescheduled["run_count"] == 0
        assert rescheduled["reference_mean"] is None
        assert rescheduled["cems_mean"] is None
        assert rescheduled["mean_difference"] is None
        assert rescheduled["confidence_coefficient"] is None
        assert rescheduled["relative_accuracy_pct"] is None
        assert rescheduled["bias_test_failed"] is False
        assert rescheduled["bias_adjustment_factor"] == 1.0
        assert rescheduled["ra_basis"] == "REFERENCE_MEAN"
        assert rescheduled["window_start_utc"] == "2026-04-06T00:00:00Z"
        assert rescheduled["applicable_standard_value"] == 0.500, (
            "the reschedule is a partial reset: the standard is retained"
        )

    def test_a_passed_second_attempt_terminates_the_cycle(self):
        """The passing evaluate keeps attempt_number at 2 and blocks a reschedule.

        PRD: "`PASSED` and `VOIDED` are the two terminal outcomes; `FAILED` is
        not terminal, precisely because of this loop."

        Design: Difficulty/non_linear_state_machine/non_linear_rata_test_cycles_back_to_scheduled_and_bumps_attempt_number
        """
        station = self._failed_audit()
        rata_test_id = station["rata_test"]["id"]

        validate_success(
            api_client.reschedule_rata_test(
                rata_test_id,
                {
                    "window_start_utc": "2026-04-06T00:00:00Z",
                    "window_end_utc": "2026-04-07T00:00:00Z",
                },
                fx.QA,
            )
        )
        fx.record_rata_runs(rata_test_id, RUN_SET_A)
        passed = fx.evaluate_rata_test(rata_test_id)

        assert passed["cems_mean"] == 0.2481
        assert passed["mean_difference"] == 0.0219
        assert passed["relative_accuracy_pct"] == 10.0
        assert passed["status"] == "PASSED"
        assert passed["bias_test_failed"] is True
        assert passed["bias_adjustment_factor"] == 1.0883
        assert passed["attempt_number"] == 2, (
            "a successful evaluate does not bump the attempt counter"
        )

        blocked = api_client.reschedule_rata_test(
            rata_test_id,
            {
                "window_start_utc": "2026-04-08T00:00:00Z",
                "window_end_utc": "2026-04-09T00:00:00Z",
            },
            fx.QA,
        )
        validate_error(blocked, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)
        assert _read_test(rata_test_id)["status"] == "PASSED"


class TestPassThresholdBoundary:
    """10.0 percent passes; 10.7 does not."""

    def _two_audits(self):
        station = fx.setup_scheduled_rata_test(
            parameter="NOX_RATE", span_value=0.800, online=True
        )
        station["failing_test"] = validate_success(
            api_client.schedule_rata_test(
                station["system"]["id"],
                rata_test_payload(
                    window_start_utc="2026-04-04T00:00:00Z",
                    window_end_utc="2026-04-05T00:00:00Z",
                ),
                fx.QA,
            ),
            201,
        )
        fx.record_rata_runs(station["rata_test"]["id"], RUN_SET_A)
        fx.record_rata_runs(station["failing_test"]["id"], RUN_SET_B)
        return station

    def test_relative_accuracy_exactly_at_the_threshold_passes(self):
        """10.0 percent passes.

        PRD: "The audit `PASSED` when that percentage is **at or below** 10.0 —
        the pass threshold is 10.0 for every monitored parameter, and equality
        passes — and `FAILED` when it is strictly above."

        Design: Difficulty/boundary_precision_check/boundary_relative_accuracy_exactly_ten_percent_passes
        """
        station = self._two_audits()

        passing = fx.evaluate_rata_test(station["rata_test"]["id"])
        assert passing["reference_mean"] == 0.2700
        assert passing["cems_mean"] == 0.2481
        assert passing["mean_difference"] == 0.0219
        assert passing["confidence_coefficient"] == 0.0050, (
            "the t value for 9 runs is 1.860"
        )
        assert passing["relative_accuracy_pct"] == 10.0
        assert passing["status"] == "PASSED"
        assert passing["bias_test_failed"] is True
        assert passing["bias_adjustment_factor"] == 1.0883

        system = validate_success(
            api_client.get_monitoring_system(station["system"]["id"], fx.QA)
        )
        assert system["bias_adjustment_factor"] == 1.0, (
            "the system is not CERTIFIED, so the passing factor is not adopted yet"
        )

    def test_a_small_shift_in_the_monitor_mean_pushes_the_audit_past_the_threshold(self):
        """A 0.0025 shift in cems_mean moves the accuracy from 10.0 to 10.7.

        PRD: "`relative_accuracy_pct` is the absolute value of `mean_difference`
        plus the absolute value of `confidence_coefficient`, divided by the chosen
        denominator, multiplied by 100, and rounded half up to one decimal place."

        Design: Difficulty/boundary_precision_check/boundary_relative_accuracy_exactly_ten_percent_passes
        """
        station = self._two_audits()

        passing = fx.evaluate_rata_test(station["rata_test"]["id"])
        failing = fx.evaluate_rata_test(station["failing_test"]["id"])

        assert failing["cems_mean"] == 0.2456
        assert failing["mean_difference"] == 0.0244
        assert failing["confidence_coefficient"] == 0.0046
        assert failing["relative_accuracy_pct"] == 10.7
        assert failing["status"] == "FAILED"

        assert (
            round(passing["cems_mean"] - failing["cems_mean"], 4) == 0.0025
        ), (
            "the two run sets share a reference mean and differ only by 0.0025 "
            "in the monitor mean"
        )
        assert failing["reference_mean"] == passing["reference_mean"]
