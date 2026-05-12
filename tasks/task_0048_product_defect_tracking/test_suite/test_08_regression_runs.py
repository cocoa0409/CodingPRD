"""Regression runs: queue, start (with cooldown), complete (with reopen
feedback on FAILED of VERIFIED), and the close-gate that blocks closing
defects with non-passed runs.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_clock,
    assign_defect,
    complete_regression_run,
    create_regression_run,
    fetch_defect,
    latest_fix_record,
    regression_complete_payload,
    regression_run_payload,
    setup_basic_module,
    setup_defect_in_state,
    start_progress,
    start_regression_run,
    submit_fix,
    verify_defect,
    verify_payload,
)


class TestRegressionQueue:
    def test_queue_regression_on_fixed_defect(self):
        """PRD §3.10: "The parent defect must be in FIXED or VERIFIED —
        earlier or already-closed states are not eligible. ... On a
        successful queue the new RegressionRun is born in status QUEUED,
        its module_id is copied from the defect's module_id".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        resp = api_client.create_regression_run(
            defect["id"],
            regression_run_payload(
                test_suite_key="smoke",
                impact_scope=[module["id"]],
            ),
            team.release_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "QUEUED"
        assert data["module_id"] == module["id"]

    def test_queue_regression_with_scope_missing_module_rejected(self):
        """PRD §3.10: "the defect's own module_id must be present in
        impact_scope, otherwise ERR_REGRESSION_INVALID_SCOPE."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        resp = api_client.create_regression_run(
            defect["id"],
            regression_run_payload(
                test_suite_key="smoke",
                impact_scope=["00000000-0000-0000-0000-000000000000"],
            ),
            team.release_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REGRESSION_INVALID_SCOPE.value,
        )


class TestRegressionStart:
    def test_start_non_queued_run_rejected(self):
        """PRD §3.10: "Starting a non-QUEUED run is ERR_REGRESSION_NOT_QUEUED."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        run = create_regression_run(team, defect)
        start_regression_run(team, run)
        # Now status=RUNNING; second start should be refused.
        resp = api_client.start_regression_run(
            run["id"], team.release_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REGRESSION_NOT_QUEUED.value,
        )

    def test_cooldown_blocks_second_start_within_window(self):
        """PRD §3.10: "A same-module cooldown is enforced at start: ...
        the start is permitted only when the project's current
        clock_minute minus that prior run's started_at_minute is at
        least 10 minutes — equality at exactly 10 minutes permits the
        start (the boundary is inclusive). A start attempted within the
        cooldown window is rejected with ERR_REGRESSION_COOLDOWN_ACTIVE."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        run1 = create_regression_run(team, defect)
        start_regression_run(team, run1)  # started_at_minute = 0
        # Second run on same module, attempt start at clock = 9.
        # First close run1 so we can queue a fresh one.
        complete_regression_run(team, run1, result="PASSED")
        advance_clock(team.project, 9)
        run2 = create_regression_run(team, defect)
        resp = api_client.start_regression_run(
            run2["id"], team.release_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REGRESSION_COOLDOWN_ACTIVE.value,
        )

    def test_cooldown_inclusive_at_exactly_ten_minutes(self):
        """PRD §3.10: "equality at exactly 10 minutes permits the start
        (the boundary is inclusive)".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        run1 = create_regression_run(team, defect)
        start_regression_run(team, run1)
        complete_regression_run(team, run1, result="PASSED")
        advance_clock(team.project, 10)
        run2 = create_regression_run(team, defect)
        resp = api_client.start_regression_run(
            run2["id"], team.release_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "RUNNING"


class TestRegressionComplete:
    def test_complete_passed_transitions_to_passed(self):
        """PRD §3.10: "A PASSED result transitions the run to PASSED and
        stops there."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        run = create_regression_run(team, defect)
        start_regression_run(team, run)
        resp = api_client.complete_regression_run(
            run["id"],
            regression_complete_payload(result="PASSED"),
            team.release_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "PASSED"

    def test_complete_non_running_rejected(self):
        """PRD §3.10: "The run must currently be in RUNNING; calling
        complete on anything else is ERR_REGRESSION_NOT_RUNNING."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        run = create_regression_run(team, defect)  # status=QUEUED
        resp = api_client.complete_regression_run(
            run["id"],
            regression_complete_payload(result="PASSED"),
            team.release_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REGRESSION_NOT_RUNNING.value,
        )

    def test_failed_run_on_verified_defect_reopens_defect(self):
        """PRD §3.10: "A FAILED result transitions the run to FAILED, and
        then — and this is the feedback loop — if the parent defect's
        status is VERIFIED at that moment, the defect is reopened: the
        reopen cascade fires in full just as it does on a verification
        failure (the reopen_count increments, the priority_score is
        recomputed, the response_due_minute resets to current
        clock_minute plus the freshly-recomputed effective response
        budget, the escalation_level resets to 0".
        """
        team, module = setup_basic_module()
        # Drive to VERIFIED first.
        defect = setup_defect_in_state(team, module, "VERIFIED")
        # Queue a regression on the VERIFIED defect.
        run = create_regression_run(team, defect)
        start_regression_run(team, run)
        complete_regression_run(team, run, result="FAILED")
        d_after = fetch_defect(team, defect["id"])
        assert d_after["status"] == "REOPENED"
        assert d_after["reopen_count"] == 1
        assert d_after["escalation_level"] == 0


class TestCloseRegressionGate:
    def test_close_with_failed_regression_rejected(self):
        """PRD §3.9: "if any RegressionRun rows exist for this defect,
        every one of them must be in PASSED; if any are still QUEUED,
        RUNNING, or FAILED, the close is refused with
        ERR_REGRESSION_NOT_PASSED."
        """
        team, module = setup_basic_module()
        # Drive defect to VERIFIED.
        defect = setup_defect_in_state(team, module, "VERIFIED")
        # Create a regression and complete it FAILED. The defect
        # reopens. Drive it back to VERIFIED and try to close.
        run = create_regression_run(team, defect)
        start_regression_run(team, run)
        complete_regression_run(team, run, result="FAILED")
        # The defect should now be REOPENED. Drive it back to VERIFIED
        # without creating yet another regression.
        assign_defect(team, defect)
        start_progress(team, defect)
        submit_fix(team, defect, fix_version="1.0.2")
        verify_defect(team, defect, outcome="PASSED")
        # Now defect is VERIFIED again; a FAILED regression run exists.
        resp = api_client.close_defect(
            defect["id"], team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REGRESSION_NOT_PASSED.value,
        )

    def test_close_with_no_regression_runs_succeeds(self):
        """PRD §3.9: "A defect that has zero RegressionRun rows may close
        without regression — the suite is optional, not mandatory."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "VERIFIED")
        resp = api_client.close_defect(
            defect["id"], team.triage_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "CLOSED"

    def test_close_with_all_passed_regression_runs_succeeds(self):
        """PRD §3.9: "if any RegressionRun rows exist for this defect,
        every one of them must be in PASSED".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "VERIFIED")
        run = create_regression_run(team, defect)
        start_regression_run(team, run)
        complete_regression_run(team, run, result="PASSED")
        resp = api_client.close_defect(
            defect["id"], team.triage_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "CLOSED"
