"""Position close guards, worker termination cascades, and clock-sweep row states."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    create_applied_worker_change,
    create_position_record,
    create_worker_record,
    get_success_data,
    list_assignment_rows,
    setup_worker_with_field,
    validate_error,
    validate_success,
)

TEST_ANALYST = TEST_USERS["analyst_headers"]


class TestPositionClose:
    def test_position_close_blocked_while_subtree_occupied_then_succeeds(self, api, analyst_headers):
        """PRD §3.2: "Closing a position moves `ACTIVE` to `CLOSED` and is guarded
        by occupancy: no worker may hold an assignment row whose interval covers
        the current logical clock date anywhere in the position's subtree, the
        position itself included. Closing while that filled headcount is above
        zero is rejected with `ERR_POSITION_SUBTREE_OCCUPIED`; closing an
        already-closed position fails with `ERR_POSITION_NOT_ACTIVE`."
        PRD §3.3: "The cascade reshapes the timeline: the assignment row covering
        the termination date is truncated so its `effective_end_date` becomes the
        termination date (the row re-derives its `row_status` on the next sweep),
        every row starting after the termination date is `VOIDED`, the worker's
        `termination_date` is recorded, and the worker's `version` increments by
        one."

        Design: Corner/state_machines/position_close_blocked_while_subtree_occupied_then_succeeds
        """
        pos = create_position_record(headcount_budget=2)
        worker = create_worker_record(pos["id"], worker_number="W720")

        err = api.close_position(pos["id"], analyst_headers)
        validate_error(err, ApiErrorId.ERR_POSITION_SUBTREE_OCCUPIED)

        validate_success(
            api.terminate_worker(worker["id"], {"termination_date": "2026-06-01"}, analyst_headers)
        )
        # PRD §3.3: the truncated row "re-derives its `row_status` on the next
        # sweep" — advance the clock so the sweep runs before the retry close.
        advance_clock("2026-08-02T00:00:00Z")

        closed = validate_success(api.close_position(pos["id"], analyst_headers))
        assert closed["status"] == "CLOSED"

    def test_close_closed_position_rejected(self, api, analyst_headers):
        """PRD §3.2: "Closing while that filled headcount is above zero is
        rejected with `ERR_POSITION_SUBTREE_OCCUPIED`; closing an already-closed
        position fails with `ERR_POSITION_NOT_ACTIVE`."

        Design: Corner/state_machines/close_closed_position_rejected
        """
        pos = create_position_record(title="Empty", headcount_budget=1)
        closed = validate_success(api.close_position(pos["id"], analyst_headers))
        assert closed["status"] == "CLOSED"

        err = api.close_position(pos["id"], analyst_headers)
        validate_error(err, ApiErrorId.ERR_POSITION_NOT_ACTIVE)

    def test_create_position_under_closed_parent_rejected(self, api, analyst_headers):
        """PRD §3.2: "The named parent must exist and be `ACTIVE`, otherwise the
        create fails with `ERR_POSITION_NOT_ACTIVE`, and the resulting reporting
        chain may be at most ten levels deep; a deeper chain is rejected with
        `ERR_HIERARCHY_DEPTH_EXCEEDED`."

        Design: Corner/validations/create_position_under_closed_parent_rejected
        """
        parent = create_position_record(title="Parent", headcount_budget=3)
        validate_success(api.close_position(parent["id"], analyst_headers))

        resp = api.create_position(
            {
                "title": "Child",
                "department": "ENG",
                "parent_position_id": parent["id"],
                "headcount_budget": 1,
            },
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_POSITION_NOT_ACTIVE)

    def test_hierarchy_depth_limit_rejected(self, api, analyst_headers):
        """PRD §3.2: "The named parent must exist and be `ACTIVE`, otherwise the
        create fails with `ERR_POSITION_NOT_ACTIVE`, and the resulting reporting
        chain may be at most ten levels deep; a deeper chain is rejected with
        `ERR_HIERARCHY_DEPTH_EXCEEDED`."

        Design: Corner/validations/hierarchy_depth_limit_rejected
        """
        parent_id = None
        for depth in range(1, 11):  # P1 (root, depth 1) .. P10 (depth 10)
            payload = {
                "title": f"P{depth}",
                "department": "HQ",
                "headcount_budget": 1,
            }
            if parent_id is not None:
                payload["parent_position_id"] = parent_id
            pos = validate_success(api.create_position(payload, analyst_headers), expected_status=201)
            parent_id = pos["id"]

        resp = api.create_position(
            {
                "title": "P11",
                "department": "HQ",
                "parent_position_id": parent_id,
                "headcount_budget": 1,
            },
            analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HIERARCHY_DEPTH_EXCEEDED)


class TestWorkerTermination:
    def test_terminate_worker_truncates_covering_row_and_voids_future_rows(self, api):
        """PRD §3.3: "The cascade reshapes the timeline: the assignment row
        covering the termination date is truncated so its `effective_end_date`
        becomes the termination date (the row re-derives its `row_status` on the
        next sweep), every row starting after the termination date is `VOIDED`,
        the worker's `termination_date` is recorded, and the worker's `version`
        increments by one."

        Design: Corner/state_machines/terminate_worker_truncates_covering_row_and_voids_future_rows
        """
        env = setup_worker_with_field(
            worker_number="W721", field_key="assignment.location_code", channels=[],
        )
        worker = env["worker"]
        field = env["field"]
        applied = create_applied_worker_change(
            worker["id"], worker["version"], field["id"], new_value="SF",
        )
        assert applied["status"] == "APPLIED"

        terminated = validate_success(
            api.terminate_worker(worker["id"], {"termination_date": "2026-08-10"}, TEST_ANALYST)
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_date"] == "2026-08-10"

        rows = list_assignment_rows(worker["id"])
        assert len(rows) == 2
        r1, r2 = rows[0], rows[1]
        assert r1["effective_end_date"] == "2026-08-10"
        assert r2["effective_start_date"] == "2026-09-01"
        assert r2["row_status"] == "VOIDED"

    def test_terminate_worker_state_and_date_guards(self, api, analyst_headers):
        """PRD §3.3: "Terminating a worker who is not `ACTIVE` fails with
        `ERR_WORKER_NOT_ACTIVE`, and a `termination_date` earlier than the
        worker's `hire_date` is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/terminate_worker_state_and_date_guards
        """
        pos = create_position_record()
        wa = create_worker_record(pos["id"], worker_number="W722", legal_name="WA")
        wb = create_worker_record(pos["id"], worker_number="W723", legal_name="WB")

        validate_success(
            api.terminate_worker(wa["id"], {"termination_date": "2026-07-01"}, analyst_headers)
        )
        err1 = api.terminate_worker(wa["id"], {"termination_date": "2026-07-01"}, analyst_headers)
        validate_error(err1, ApiErrorId.ERR_WORKER_NOT_ACTIVE)

        err2 = api.terminate_worker(wb["id"], {"termination_date": "2026-01-04"}, analyst_headers)
        validate_error(err2, ApiErrorId.ERR_INVALID_REQUEST)


class TestClockSweepRowStates:
    def test_clock_sweep_activates_future_assignment_row(self, api):
        """PRD §2.5: "Each clock advance re-evaluates every time-driven rule in
        the system: assignment rows derive their `row_status` from the clock
        relative to their interval (`FUTURE` rows whose start has been reached
        become `ACTIVE`; rows whose end has been reached or passed become
        `HISTORY`; a future row whose entire interval has elapsed moves directly
        from `FUTURE` to `HISTORY`)"

        Design: Corner/state_machines/clock_sweep_activates_future_assignment_row
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W724", hire_date="2026-09-01")
        rows = list_assignment_rows(worker["id"])
        assert rows[0]["row_status"] == "FUTURE"

        advance_clock("2026-09-01T00:00:00Z")
        rows = list_assignment_rows(worker["id"])
        assert rows[0]["row_status"] == "ACTIVE"

    def test_clock_sweep_ages_assignment_row_to_history(self, api, analyst_headers):
        """PRD §2.5: "Each clock advance re-evaluates every time-driven rule in
        the system: assignment rows derive their `row_status` from the clock
        relative to their interval (`FUTURE` rows whose start has been reached
        become `ACTIVE`; rows whose end has been reached or passed become
        `HISTORY`; a future row whose entire interval has elapsed moves directly
        from `FUTURE` to `HISTORY`)"

        Design: Corner/state_machines/clock_sweep_ages_assignment_row_to_history
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W725")
        validate_success(
            api.terminate_worker(worker["id"], {"termination_date": "2026-06-01"}, analyst_headers)
        )

        advance_clock("2026-08-02T00:00:00Z")
        rows = list_assignment_rows(worker["id"])
        assert len(rows) == 1
        assert rows[0]["effective_end_date"] == "2026-06-01"
        assert rows[0]["row_status"] == "HISTORY"

    def test_clock_sweep_skips_future_row_to_history(self, api, analyst_headers):
        """PRD §2.5: "Each clock advance re-evaluates every time-driven rule in
        the system: assignment rows derive their `row_status` from the clock
        relative to their interval (`FUTURE` rows whose start has been reached
        become `ACTIVE`; rows whose end has been reached or passed become
        `HISTORY`; a future row whose entire interval has elapsed moves directly
        from `FUTURE` to `HISTORY`)"

        Design: Corner/state_machines/clock_sweep_skips_future_row_to_history
        """
        pos = create_position_record()
        worker = create_worker_record(pos["id"], worker_number="W726", hire_date="2026-09-01")
        validate_success(
            api.terminate_worker(worker["id"], {"termination_date": "2026-09-15"}, analyst_headers)
        )

        advance_clock("2026-09-16T00:00:00Z")
        rows = list_assignment_rows(worker["id"])
        assert len(rows) == 1
        assert rows[0]["effective_start_date"] == "2026-09-01"
        assert rows[0]["effective_end_date"] == "2026-09-15"
        assert rows[0]["row_status"] == "HISTORY"
