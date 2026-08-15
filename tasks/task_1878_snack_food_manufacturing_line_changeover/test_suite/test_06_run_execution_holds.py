"""Run execution and quality as parallel state dimensions: holds, releases,
completion gates, and the oil-breach cascade into display cases."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_run,
    create_display_case,
    create_line,
    create_plain_product,
    disposition_run,
    get_line_fryer_oil,
    get_success_data,
    make_line_operator_headers,
    make_quality_tech_headers,
    record_weight_check,
    record_weight_checks,
    schedule_run,
    set_clock,
    setup_active_promo_window,
    setup_running_run,
    setup_system_held_run,
    start_run,
    validate_error,
    validate_paginated,
)

PM = TEST_USERS["plant_manager_headers"]


class TestParallelDimensions:
    def test_hold_release_cycle_leaves_quality_pending(self, api):
        """PRD §3.4: "A `LineOperator` may also place a hold directly on a
        `RUNNING` run, moving it to `HELD` with `hold_placed_by_user_id` set to
        the caller's `X-User-ID`"
        PRD §3.4: "A successful release clears `hold_placed_by_user_id` to
        null, returns the run to `RUNNING`, and recomputes posture."

        Design: Difficulty/non_linear_state_machine/run_execution_quality_parallel_dimensions
        """
        ctx = setup_running_run()
        run_id = ctx["run"]["id"]
        held = get_success_data(
            api.place_hold(run_id, make_line_operator_headers("op-1")))
        # execution moves while the quality axis stays untouched
        assert held["execution_status"] == "HELD"
        assert held["quality_status"] == "PENDING"
        assert held["hold_placed_by_user_id"] == "op-1"
        released = get_success_data(
            api.release_hold(run_id, make_quality_tech_headers("qt-2")))
        assert released["execution_status"] == "RUNNING"
        assert released["quality_status"] == "PENDING"
        assert released["hold_placed_by_user_id"] is None

    def test_completion_and_disposition_leave_execution_completed(self, api):
        """PRD §3.5: "The run's `quality_status` moves from `PENDING` to
        `QHOLD` when any of four conditions holds: ... or the absolute
        deviation of `seasoning_actual_pct` from `seasoning_target_pct` exceeds
        half a percentage point (exactly half a point passes)."
        PRD §3.5: "A `PASS` sets `quality_status` to `PASSED`."

        Design: Difficulty/non_linear_state_machine/run_execution_quality_parallel_dimensions
        """
        ctx = setup_running_run()
        run_id = ctx["run"]["id"]
        record_weight_check(run_id, bag_weight_g=100.0,
                            lbs_fried_since_last_check=100, avg_fry_temp_c=180.0)
        # seasoning deviation 0.51 > 0.5 forces QHOLD on the quality axis
        completed = complete_run(run_id, seasoning_actual_pct=4.51)
        assert completed["execution_status"] == "COMPLETED"
        assert completed["quality_status"] == "QHOLD"
        passed = disposition_run(run_id, "PASS", tech_id="qt-2")
        assert passed["execution_status"] == "COMPLETED"
        assert passed["quality_status"] == "PASSED"


class TestThreeLinkOilCascade:
    def _setup_cascade(self, api):
        """Running run with a PLANNED display case, oil at tpm 20.5."""
        ctx = setup_active_promo_window(quota_total_cases=10)
        line = create_line()
        run = schedule_run(line["id"], ctx["product"]["id"],
                           start="2026-08-02T08:00:00Z",
                           end="2026-08-02T16:00:00Z",
                           lbs_planned=20000, cases_planned=100)
        set_clock("2026-08-02T08:00:00Z")
        start_run(run["id"])
        dc = create_display_case(ctx["window"]["id"], run["id"], 5)
        assert get_success_data(api.get_run(run["id"], PM))["cases_unrouted"] == 95
        record_weight_checks(run["id"], [(100.1, 5000, 180.0),
                                         (100.1, 5000, 180.0)])
        return {"window": ctx["window"], "product": ctx["product"],
                "line": line, "run": run, "dc": dc}

    def test_breach_holds_oil_then_run(self, api):
        """PRD §3.4: "The `QUALITY_HOLD` transition is a cascade, not a flag.
        When oil crosses the threshold while a run is `RUNNING` on the line,
        that run is forced from `RUNNING` to `HELD` with
        `hold_placed_by_user_id` set to null — a system hold."

        Design: Difficulty/transitive_cascade/weight_check_tpm_breach_three_link_cascade
        """
        ctx = self._setup_cascade(api)
        # link 1: the third check pushes stored tpm to exactly 27.0
        record_weight_check(ctx["run"]["id"], bag_weight_g=100.1,
                            lbs_fried_since_last_check=3250, avg_fry_temp_c=180.0)
        oil = get_line_fryer_oil(ctx["line"]["id"])
        assert oil["tpm_pct"] == pytest.approx(27.0)
        assert oil["state"] == "QUALITY_HOLD"
        # link 2: the RUNNING run is force-held by the system
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["execution_status"] == "HELD"
        assert run["hold_placed_by_user_id"] is None

    def test_hold_cascade_cancels_planned_display_cases(self, api):
        """PRD §3.4: "The hold in turn cascades: every DisplayCase against
        that run still in `PLANNED` status is cancelled with `cancelled_reason`
        `OIL_HOLD`, releasing its case reservation."
        PRD §2.10: "cancellations release their reservations back into it."

        Design: Difficulty/transitive_cascade/weight_check_tpm_breach_three_link_cascade
        """
        ctx = self._setup_cascade(api)
        record_weight_check(ctx["run"]["id"], bag_weight_g=100.1,
                            lbs_fried_since_last_check=3250, avg_fry_temp_c=180.0)
        # link 3: the run's PLANNED display case is cancelled by the hold
        dc = get_success_data(api.get_display_case(ctx["dc"]["id"], PM))
        assert dc["status"] == "CANCELLED"
        assert dc["cancelled_reason"] == "OIL_HOLD"
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["cases_unrouted"] == 100, "the reservation must be released"


class TestExecutionInvalidTransitions:
    def test_run_start_from_running_rejected(self, api):
        """PRD §3.4: "The run must be `SCHEDULED` and no sibling run on the
        same line may already be `RUNNING`; either violation is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/run_start_from_running_rejected
        """
        ctx = setup_running_run()
        run_id = ctx["run"]["id"]
        started_at = ctx["run"]["started_at"]
        resp = api.start_run(run_id, make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        run = get_success_data(api.get_run(run_id, PM))
        assert run["execution_status"] == "RUNNING"
        assert run["started_at"] == started_at

    def test_run_complete_from_scheduled_rejected(self, api):
        """PRD §3.5: "A `LineOperator` completes a `RUNNING` run by supplying
        the actuals"
        PRD §2.9: "the target entity occupies a from-state of the invoked
        transition, terminal entities reject all further transitions with
        `ERR_ALREADY_TERMINAL`, non-terminal mismatches yield
        `ERR_INVALID_STATE`"

        Design: Corner/state_machines/run_complete_from_scheduled_rejected
        """
        product = create_plain_product()
        line = create_line()
        run = schedule_run(line["id"], product["id"])
        resp = api.complete_run(run["id"],
                                {"lbs_produced": 100, "cases_produced": 10,
                                 "rejected_cases": 0, "seasoning_actual_pct": 4.0},
                                make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        run = get_success_data(api.get_run(run["id"], PM))
        assert run["execution_status"] == "SCHEDULED"

    def test_complete_without_weight_checks_rejected(self, api):
        """PRD §3.5: "Completion is impossible before at least one weight check
        has been recorded for the run — the attempt is rejected with
        `ERR_NO_WEIGHT_CHECKS`."

        Design: Corner/validations/complete_without_weight_checks_rejected
        """
        ctx = setup_running_run()
        resp = api.complete_run(ctx["run"]["id"],
                                {"lbs_produced": 100, "cases_produced": 10,
                                 "rejected_cases": 0, "seasoning_actual_pct": 4.0},
                                make_line_operator_headers("op-1"))
        validate_error(resp, ApiErrorId.ERR_NO_WEIGHT_CHECKS, 422)
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["execution_status"] == "RUNNING"


class TestHoldReleaseSoD:
    def test_sod_holder_cannot_release_own_hold(self, api):
        """PRD §3.4: "for user-placed holds the releaser's `X-User-ID` must
        differ from `hold_placed_by_user_id` — releasing one's own hold is
        rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/validations/sod_holder_cannot_release_own_hold
        """
        product = create_plain_product()
        line = create_line()
        run = schedule_run(line["id"], product["id"])
        set_clock("2026-08-02T08:00:00Z")
        get_success_data(api.start_run(run["id"], make_line_operator_headers("shared-1")))
        get_success_data(api.place_hold(run["id"], make_line_operator_headers("shared-1")))
        # the same user, even wearing the QualityTechnician role, cannot
        # release the hold they placed
        resp = api.release_hold(run["id"], make_quality_tech_headers("shared-1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)
        released = get_success_data(
            api.release_hold(run["id"], make_quality_tech_headers("qt-2")))
        assert released["execution_status"] == "RUNNING"
        assert released["hold_placed_by_user_id"] is None
