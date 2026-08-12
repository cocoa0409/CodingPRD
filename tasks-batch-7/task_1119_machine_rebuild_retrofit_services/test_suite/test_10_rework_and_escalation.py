"""Rework and escalation: the work-dimension cycle, the parallel commercial
dimension's independence, the acceptance-failure cascade onto shipment stages,
and the third-failure escalation threshold with RETRY resolution."""

import pytest

import test_helpers as fx
from test_helpers import (
    FAILING_SAMPLES,
    PASSING_SAMPLES,
    PM,
    round_half_up_cents,
    validate_success,
)


def test_quote_recompute_reverts_quote_sent_without_touching_work(api):
    """PRD §3.3: "Every computation increments `quote_revision` by one, clears `quote_stale` to `false`, snapshots all six money fields, and increments the project's `version` by one."
    PRD §3.3: "If the project's `commercial_status` was `QUOTE_SENT` at the moment of recomputation — a renegotiation — the commercial dimension reverts to `QUOTE_DRAFT`, leaving `work_status` untouched."

    Design: Difficulty/non_linear_state_machine/project_rework_cycle_and_parallel_commercial
    """
    ctx = fx.setup_project_decided()
    project_id = ctx.project["id"]

    first = fx.compute_quote(project_id)
    assert first["quote_revision"] == 1
    fx.send_quote(project_id)
    sent = fx.get_project(project_id)
    assert sent["commercial_status"] == "QUOTE_SENT"
    assert sent["work_status"] == "DECIDED"

    recomputed = fx.compute_quote(project_id)
    assert recomputed["commercial_status"] == "QUOTE_DRAFT"
    assert recomputed["quote_revision"] == 2
    assert recomputed["work_status"] == "DECIDED"
    assert recomputed["quote_stale"] is False
    assert recomputed["version"] == sent["version"] + 1


def test_rework_cycle_leaves_commercial_dimension_untouched(api):
    """PRD §3.6: "In both outcomes below, the project's `rework_count` increases by one, its `rework_cost_cents` accumulates a surcharge of five percent of the current `quote_price_cents` rounded half-up to a whole cent — the quote price itself is never recomputed by rework, the surcharge accumulates separately — and every `PLANNED` ShipmentStage of the project is parked `ON_HOLD`."
    PRD §3.3: "The commercial dimension runs in parallel with the work dimension: quote sends, approvals, and renegotiation reverts never move `work_status`, and work transitions never move `commercial_status`."
    PRD §3.6: "A passing recording moves the test to the terminal `PASSED` and fires the acceptance cascade on the project: `work_status` moves from `AWAITING_ACCEPTANCE` to `ACCEPTED`, `consecutive_fail_count` resets to zero, the project's `accepted_positioning_microns` — null until this moment — is set to the passing test's `max_abs_sample_microns`, and a TrainingRecord is auto-created in `PLANNED` with its `sessions_required` derived from the decision class."

    Design: Difficulty/non_linear_state_machine/project_rework_cycle_and_parallel_commercial
    """
    ctx = fx.setup_scheduled_test(decision="MECHANICAL_REBUILD")
    project_id = ctx.project["id"]
    quote_price = fx.get_project(project_id)["quote_price_cents"]

    failed = fx.record_test(ctx.test["id"], samples=FAILING_SAMPLES, repeatability=5.0)
    assert failed["status"] == "FAILED"

    project = fx.get_project(project_id)
    assert project["work_status"] == "REWORK"
    assert project["rework_count"] == 1
    assert project["consecutive_fail_count"] == 1
    assert project["rework_cost_cents"] == round_half_up_cents(quote_price * 0.05)
    assert project["quote_price_cents"] == quote_price
    assert project["commercial_status"] == "APPROVED"

    # Rework cycle: declare readiness again, schedule attempt number 2, pass it.
    fx.declare_ready(project_id, engineer_id=ctx.engineer_id)
    second_test = fx.schedule_acceptance_test(project_id, inspector_id=ctx.inspector_id)
    assert second_test["attempt_number"] == 2

    passed = fx.record_test(second_test["id"], samples=PASSING_SAMPLES, repeatability=5.0)
    assert passed["status"] == "PASSED"

    project = fx.get_project(project_id)
    assert project["work_status"] == "ACCEPTED"
    assert project["consecutive_fail_count"] == 0
    assert project["accepted_positioning_microns"] == pytest.approx(8.0, abs=0.001)
    assert project["commercial_status"] == "APPROVED"

    record = fx.find_training_record_for_project(project_id)
    assert record["status"] == "PLANNED"
    assert record["sessions_required"] == 2


class TestAcceptanceFailCascadeOntoStages:
    def _setup_with_planned_stage(self, api):
        ctx = fx.setup_scheduled_test(decision="MECHANICAL_REBUILD")
        window = fx.create_window(ctx.customer["id"])
        stage = fx.create_stage(ctx.project["id"], window["id"])
        assert fx.get_window(window["id"])["status"] == "LOCKED"
        ctx.window = window
        ctx.stage = stage
        return ctx

    def test_fail_moves_project_to_rework_with_surcharge(self, api):
        """PRD §3.6: "A failing recording moves the test to the terminal `FAILED` and fires the rework cascade."
        PRD §3.6: "In both outcomes below, the project's `rework_count` increases by one, its `rework_cost_cents` accumulates a surcharge of five percent of the current `quote_price_cents` rounded half-up to a whole cent — the quote price itself is never recomputed by rework, the surcharge accumulates separately — and every `PLANNED` ShipmentStage of the project is parked `ON_HOLD`."

        Design: Difficulty/transitive_cascade/acceptance_fail_cascade_depth2
        """
        ctx = self._setup_with_planned_stage(api)
        quote_price = fx.get_project(ctx.project["id"])["quote_price_cents"]

        failed = fx.record_test(ctx.test["id"], samples=FAILING_SAMPLES, repeatability=5.0)
        assert failed["status"] == "FAILED"

        project = fx.get_project(ctx.project["id"])
        assert project["work_status"] == "REWORK"
        assert project["rework_count"] == 1
        assert project["consecutive_fail_count"] == 1
        assert project["rework_cost_cents"] == round_half_up_cents(quote_price * 0.05)

    def test_fail_parks_planned_stage_and_leaves_window_locked(self, api):
        """PRD §3.6: "In both outcomes below, the project's `rework_count` increases by one, its `rework_cost_cents` accumulates a surcharge of five percent of the current `quote_price_cents` rounded half-up to a whole cent — the quote price itself is never recomputed by rework, the surcharge accumulates separately — and every `PLANNED` ShipmentStage of the project is parked `ON_HOLD`."
        PRD §3.5: "The first shipment stage that references it locks it, moving it to `LOCKED`, which is a one-way ratchet: a `LOCKED` window can no longer be cancelled, while an `OPEN` window may be cancelled to `CANCELLED` by its customer or a logistics coordinator (attempting to cancel a window that is not `OPEN` fails with `ERR_INVALID_STATE`)."

        Design: Difficulty/transitive_cascade/acceptance_fail_cascade_depth2
        """
        ctx = self._setup_with_planned_stage(api)
        fx.record_test(ctx.test["id"], samples=FAILING_SAMPLES, repeatability=5.0)

        stage_after = fx.get_stage(ctx.stage["id"])
        assert stage_after["status"] == "ON_HOLD"

        window_after = fx.get_window(ctx.window["id"])
        assert window_after["status"] == "LOCKED"


def test_escalation_on_third_consecutive_failure(api):
    """PRD §3.6: "The destination depends on the failure streak: the project's `consecutive_fail_count` increases by one, and if that brought the streak below three the project falls back to `REWORK`, from which the engineer may again declare readiness; if the streak thereby reaches exactly three, the project instead falls to `ESCALATED` with `consecutive_fail_count` standing at three."
    PRD §3.6: "A `RETRY` resolution moves the project from `ESCALATED` back to `AWAITING_ACCEPTANCE`, resets `consecutive_fail_count` to zero, increments `escalation_count` by one, and accumulates a steeper surcharge of ten percent of the current `quote_price_cents` rounded half-up to a whole cent into `rework_cost_cents`."

    Design: Corner/state_machines/escalation_on_third_consecutive_failure
    """
    ctx = fx.setup_scheduled_test(decision="MECHANICAL_REBUILD")
    project_id = ctx.project["id"]
    quote_price = fx.get_project(project_id)["quote_price_cents"]
    fail_surcharge = round_half_up_cents(quote_price * 0.05)

    # Three consecutive failures, re-declaring readiness between attempts.
    test = ctx.test
    for attempt in (1, 2, 3):
        if attempt > 1:
            fx.declare_ready(project_id, engineer_id=ctx.engineer_id)
            test = fx.schedule_acceptance_test(project_id, inspector_id=ctx.inspector_id)
            assert test["attempt_number"] == attempt
        recorded = fx.record_test(test["id"], samples=FAILING_SAMPLES, repeatability=5.0)
        assert recorded["status"] == "FAILED"

    project = fx.get_project(project_id)
    assert project["work_status"] == "ESCALATED"
    assert project["consecutive_fail_count"] == 3
    assert project["rework_count"] == 3
    assert project["rework_cost_cents"] == 3 * fail_surcharge

    resolved = validate_success(
        api.resolve_escalation(project_id, {"action": "RETRY"}, PM), 200
    )
    assert resolved["work_status"] == "AWAITING_ACCEPTANCE"
    assert resolved["consecutive_fail_count"] == 0
    assert resolved["escalation_count"] == 1
    assert resolved["rework_cost_cents"] == (
        3 * fail_surcharge + round_half_up_cents(quote_price * 0.10)
    )
