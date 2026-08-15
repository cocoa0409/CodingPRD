"""Difficulty: boundary precision — yield variance strict-> threshold and the
trial completion-ratio floor (PRD §3.4, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_production_batch,
    setup_locked_formula,
    setup_trial_protocol,
    validate_error,
    validate_success,
)


class TestYieldVarianceExactlyAtHoldThreshold:
    def _two_in_process_batches(self, api, production_planner_headers,
                                line_operator_headers):
        ctx = setup_locked_formula()
        b1 = create_production_batch(
            ctx["formula"]["id"], planned_kg=1000.0, line_id="LINE-C",
            scheduled_start="2026-08-12T08:00:00Z",
        )
        b2 = create_production_batch(
            ctx["formula"]["id"], planned_kg=1000.0, line_id="LINE-D",
            scheduled_start="2026-08-12T08:00:00Z",
        )
        for batch in (b1, b2):
            validate_success(api.release_batch(batch["id"], production_planner_headers))
            validate_success(api.start_run(batch["id"], line_operator_headers))
        return ctx, b1, b2

    def test_boundary_exactly_5_percent_passes_without_override(
        self, api, production_planner_headers, line_operator_headers
    ):
        """PRD §3.6: "A variance of exactly 5.00 percent passes without an
        override — the threshold is strict."
        PRD §3.6: "A batch's `yield_variance_pct` is the difference between
        `actual_kg` and `planned_kg`, divided by `planned_kg`, expressed as a
        percentage and rounded half up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/yield_variance_exactly_at_hold_threshold
        """
        _ctx, b1, _b2 = self._two_in_process_batches(
            api, production_planner_headers, line_operator_headers
        )
        completed = validate_success(
            api.complete_batch(b1["id"], {"actual_kg": 1050.0}, line_operator_headers)
        )
        assert completed["yield_variance_pct"] == pytest.approx(5.0, abs=0.005)
        assert completed["status"] == "COMPLETED"

    def test_above_threshold_rejected_without_override(
        self, api, production_planner_headers, line_operator_headers
    ):
        """PRD §3.6: "When its absolute value is strictly greater than 5.00
        percent, the completion request must carry the `override` flag and be
        acted on by a `QualityAnalyst`; a completion breaching the threshold
        without the override is rejected with `ERR_YIELD_VARIANCE_HOLD`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/yield_variance_exactly_at_hold_threshold
        """
        _ctx, _b1, b2 = self._two_in_process_batches(
            api, production_planner_headers, line_operator_headers
        )
        resp = api.complete_batch(b2["id"], {"actual_kg": 1051.0}, line_operator_headers)
        # (1051 - 1000) / 1000 * 100 == 5.10 > 5.00 -> held without override.
        validate_error(resp, ApiErrorId.ERR_YIELD_VARIANCE_HOLD.value)


class TestTrialCompletionRatioExactlyAtPassFloor:
    def test_ratio_exactly_075_routes_to_passed(self, api, qa_approver_headers):
        """PRD §3.4: "Recording a verdict routes on the recomputed ratio: a
        `completion_ratio` of 0.75 or higher moves the protocol from `ANALYSIS`
        to `PASSED`, while a ratio below 0.75 moves it to `FAILED`."
        PRD §3.4: "its `completion_ratio` — the `completed_count` divided by the
        `animal_count` — is kept at 4 decimal places."

        Design: Difficulty/boundary_precision_check/trial_completion_ratio_exactly_at_pass_floor
        """
        ctx = setup_trial_protocol(target_state="ANALYSIS", animal_count=8, completed_count=6)
        assert ctx["protocol"]["completion_ratio"] == pytest.approx(0.75, abs=0.00005)
        verdict = validate_success(api.record_verdict(ctx["protocol"]["id"], qa_approver_headers))
        assert verdict["completion_ratio"] == pytest.approx(0.75, abs=0.00005)
        assert verdict["status"] == "PASSED"

    def test_ratio_below_floor_routes_to_failed(self, api, qa_approver_headers):
        """PRD §3.4: "Recording a verdict routes on the recomputed ratio: a
        `completion_ratio` of 0.75 or higher moves the protocol from `ANALYSIS`
        to `PASSED`, while a ratio below 0.75 moves it to `FAILED`. The failed
        branch is a routing outcome, not an error — the request succeeds either
        way."

        Design: Difficulty/boundary_precision_check/trial_completion_ratio_exactly_at_pass_floor
        """
        ctx = setup_trial_protocol(target_state="ANALYSIS", animal_count=8, completed_count=5)
        assert ctx["protocol"]["completion_ratio"] == pytest.approx(0.625, abs=0.00005)
        verdict = validate_success(api.record_verdict(ctx["protocol"]["id"], qa_approver_headers))
        assert verdict["completion_ratio"] == pytest.approx(0.625, abs=0.00005)
        assert verdict["status"] == "FAILED"
