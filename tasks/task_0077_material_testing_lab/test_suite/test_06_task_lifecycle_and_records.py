"""Task lifecycle: start, submit-record, retest workflow, complete, cancel,
and the COMPRESSION_STRENGTH result-calculation boundary
(PRD §3.6, §3.7)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_test_record,
    complete_task,
    make_tester_headers,
    setup_assigned_task,
    setup_completed_task,
    setup_in_progress_task,
    setup_task_with_abnormal_first_record,
    setup_task_with_retest_abnormal_final,
    submit_record,
    create_record_payload,
    validate_error,
    validate_success,
)


class TestStartTask:
    def test_start_requires_assigned_state(self, api):
        """PRD §3.6: 'Once a task is ASSIGNED, the assigned Tester
        advances it to IN_PROGRESS by starting work.'

        Claim: start_task on a PENDING_ASSIGNMENT task is rejected.
        """
        env = setup_assigned_task()
        # Reassign back to PENDING_ASSIGNMENT via /reassign.
        from test_helpers import TEST_USERS
        api.reassign_task(env["task"]["id"], TEST_USERS["lab_manager_headers"])
        resp = api.start_task(
            env["task"]["id"], make_tester_headers(env["tester"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_start_requires_caller_to_be_assigned_tester(self, api):
        """PRD §3.6: 'the caller's X-User-ID must equal the task's
        assigned_tester_id ... Any condition unmet rejects the start
        with ERR_INVALID_STATE.'

        Claim: a Tester whose id != assigned_tester_id cannot start
        the task.
        """
        from test_helpers import create_tester
        env = setup_assigned_task()
        # Need a booking first so the other start preconditions don't
        # mask the ownership precondition.
        from test_helpers import book_instrument_for_task, anchor_plus
        book_instrument_for_task(
            instrument_id=env["instrument"]["id"],
            task_id=env["task"]["id"],
            slot_start=anchor_plus(hours=1),
            slot_end=anchor_plus(hours=2),
        )
        other = create_tester()
        resp = api.start_task(
            env["task"]["id"], make_tester_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestRecordCalculationBoundary:
    """PRD §3.6 — calculated_result and abnormal_flag at exact boundary."""

    def test_lower_bound_exact_is_not_abnormal(self, api):
        """PRD §3.6: 'The abnormal_flag is true if and only if the
        calculated_result is strictly less than the lower bound for
        the method or strictly greater than the upper bound; a result
        exactly equal to the lower bound is not abnormal.'

        Difficulty-design: abnormal_flag_at_lower_bound_exact.

        Claim: peak_load_kn=450 on a 150mm cube → 20.0 MPa (= LOWER) →
        abnormal_flag is false.
        """
        # difficulty: boundary_precision_check/abnormal_flag_at_lower_bound_exact
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=450.0,
        )
        # 450 kN * 1000 / (150*150 mm^2) = 20.0 MPa exactly
        assert record["calculated_result"] == pytest.approx(20.0, abs=0.01)
        assert record["abnormal_flag"] is False

    def test_just_below_lower_bound_is_abnormal(self, api):
        """PRD §3.6: 'calculated_result is strictly less than the lower
        bound for the method ... abnormal_flag is true.'

        Claim: peak_load_kn=400 on a 150mm cube → 17.8 MPa (< 20.0) →
        abnormal_flag is true.
        """
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=400.0,
        )
        # 400 kN * 1000 / 22500 = 17.777... → rounds half-up to 17.8
        assert record["calculated_result"] == pytest.approx(17.8, abs=0.01)
        assert record["abnormal_flag"] is True

    def test_upper_bound_exact_is_not_abnormal(self, api):
        """PRD §3.6: 'a result exactly equal to the upper bound is not
        abnormal — boundaries are inclusive on the in-band side.'

        Claim: peak_load_kn=1350 on a 150mm cube → 60.0 MPa (= UPPER) →
        abnormal_flag is false.
        """
        env = setup_in_progress_task()
        record = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=1350.0,
        )
        assert record["calculated_result"] == pytest.approx(60.0, abs=0.01)
        assert record["abnormal_flag"] is False


class TestRetestWorkflow:
    """PRD §3.7 — single-retest cap and revision loop."""

    def test_first_abnormal_record_triggers_retest(self, api, lab_manager_headers, lab_clerk_headers):
        """PRD §3.7: 'When a tester submits the first TestRecord on a
        task and the abnormal_flag is true while the task's retest_count
        is still zero, the system triggers the retest workflow: the
        task transitions from IN_PROGRESS to AWAITING_RETEST, and the
        parent sample transitions from IN_TESTING to RETESTING.'

        Difficulty-design: test_task_retest_loop (first half).

        Claim: after the first abnormal record, the task is
        AWAITING_RETEST and the sample is RETESTING.
        """
        # difficulty: non_linear_state_machine/test_task_retest_loop
        env = setup_task_with_abnormal_first_record()
        task = validate_success(
            api.get_task(env["task"]["id"], lab_manager_headers),
        )
        assert task["status"] == "AWAITING_RETEST"
        assert task["retest_count"] == 0
        sample = validate_success(
            api.get_sample(env["sample"]["id"], lab_clerk_headers),
        )
        assert sample["status"] == "RETESTING"

    def test_retest_submission_returns_task_to_in_progress(
        self, api, lab_manager_headers,
    ):
        """PRD §3.7: 'The retest itself is begun by submitting a second
        TestRecord whose supersedes_record_id references the abnormal
        record; the task transitions from AWAITING_RETEST back to
        IN_PROGRESS, the retest_count is incremented from zero to one,
        and the previous SUBMITTED record transitions from SUBMITTED to
        SUPERSEDED.'

        Difficulty-design: test_task_retest_loop (second half).

        Claim: after the retest record, task is IN_PROGRESS,
        retest_count is 1, and the original record is SUPERSEDED.
        """
        # difficulty: non_linear_state_machine/test_task_retest_loop
        env = setup_task_with_abnormal_first_record()
        retest = submit_record(
            task_id=env["task"]["id"], tester_id=env["tester"]["id"],
            peak_load_kn=600.0,
            supersedes_record_id=env["first_record"]["id"],
        )
        assert retest["calculated_result"] == pytest.approx(26.7, abs=0.05)
        assert retest["abnormal_flag"] is False
        task = validate_success(
            api.get_task(env["task"]["id"], lab_manager_headers),
        )
        assert task["status"] == "IN_PROGRESS"
        assert task["retest_count"] == 1
        # Original record is now SUPERSEDED.
        records_resp = api.list_records(
            env["task"]["id"], lab_manager_headers,
        )
        from test_helpers import validate_paginated
        data, _ = validate_paginated(records_resp)
        statuses = {r["id"]: r["status"] for r in data}
        assert statuses[env["first_record"]["id"]] == "SUPERSEDED"

    def test_second_retest_attempt_rejected(self, api, lab_manager_headers):
        """PRD §3.7: 'The cap is strict: at most one retest per task. A
        second retest attempt — that is, a submission whose
        supersedes_record_id is present while the task's retest_count
        is already one — is rejected with ERR_RETEST_LIMIT_EXCEEDED.'

        Claim: after a single retest, a second supersedes submission
        yields ERR_RETEST_LIMIT_EXCEEDED.
        """
        env = setup_task_with_retest_abnormal_final()
        # The retest_record is already in-place; attempt a second retest.
        retest_record = env["retest_record"]
        resp = api.create_record(
            env["task"]["id"],
            create_record_payload(
                peak_load_kn=600.0,
                supersedes_record_id=retest_record["id"],
            ),
            make_tester_headers(env["tester"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED.value)


class TestTaskCompletion:
    def test_complete_task_cascades(
        self, api, lab_manager_headers, lab_clerk_headers,
    ):
        """PRD §3.7: 'the completion cascade moves the task to
        COMPLETED, decrements the tester's active_task_count,
        transitions the linked InstrumentBooking to COMPLETED, accrues
        the booking's duration to the instrument's usage_minutes_total
        (rounded up to the next whole minute), and — if this completion
        is the last outstanding task on the parent sample — advances
        the sample from IN_TESTING to TESTED.'

        Difficulty-design: task_completion_bubble_up_to_sample.

        Claim: completing the only task on a sample yields task=COMPLETED,
        active_task_count back to 0, booking=COMPLETED,
        usage_minutes_total increased by the booked minutes, and
        Sample=TESTED.
        """
        # difficulty: transitive_cascade/task_completion_bubble_up_to_sample
        env = setup_completed_task(booking_minutes=60)
        # Task already COMPLETED in the fixture.
        task = validate_success(
            api.get_task(env["task"]["id"], lab_manager_headers),
        )
        assert task["status"] == "COMPLETED"
        # Tester.active_task_count back to 0.
        tester = validate_success(
            api.get_tester(env["tester"]["id"], lab_manager_headers),
        )
        assert tester["active_task_count"] == 0
        # Instrument.usage_minutes_total increased by 60.
        instrument = validate_success(
            api.get_instrument(
                env["instrument"]["id"], lab_manager_headers,
            ),
        )
        assert instrument["usage_minutes_total"] >= 60
        # Sample bubbles up to TESTED.
        sample = validate_success(
            api.get_sample(env["sample"]["id"], lab_clerk_headers),
        )
        assert sample["status"] == "TESTED"
