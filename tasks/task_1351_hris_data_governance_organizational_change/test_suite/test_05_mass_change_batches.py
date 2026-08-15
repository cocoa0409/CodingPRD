"""Mass-change batches: lifecycle guards, validation cycle, execute drift, rollback, totals."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_batch_line_record,
    advance_clock,
    create_batch_record,
    create_data_field_record,
    create_position_record,
    create_scheduled_batch,
    create_worker_record,
    execute_batch_record,
    get_batch_version,
    list_assignment_rows,
    list_events,
    provision_grant,
    schedule_batch_record,
    setup_worker_with_field,
    submit_batch_record,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]


class TestBatchLifecycleGuards:
    def test_validated_batch_add_line_and_execute_rejected(self, api):
        """PRD §3.5: "While the batch is `DRAFT`, lines are added one at a time;
        adding to a non-draft batch fails with `ERR_BATCH_NOT_DRAFT`."
        PRD §3.5: "Scheduling moves `VALIDATED` to `SCHEDULED`
        (`ERR_BATCH_NOT_EXECUTABLE` otherwise) with a `scheduled_effective_date`
        that must not precede the logical clock date
        (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`); the batch's `version` increments."

        Design: Corner/state_machines/validated_batch_add_line_and_execute_rejected
        """
        env = setup_worker_with_field(
            worker_number="W746", field_key="assignment.location_code", channels=[],
        )
        batch = create_batch_record(name="guards")
        add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "SF")
        submitted = submit_batch_record(batch["id"])
        assert submitted["status"] == "VALIDATED"

        err1 = api.add_batch_line(
            batch["id"],
            {
                "line_index": 2,
                "target_worker_id": env["worker"]["id"],
                "target_field_id": env["field"]["id"],
                "new_value": "LA",
                "effective_date": "2026-10-01",
            },
            ANALYST,
        )
        validate_error(err1, ApiErrorId.ERR_BATCH_NOT_DRAFT)

        err2 = api.execute_batch(batch["id"], ANALYST)
        validate_error(err2, ApiErrorId.ERR_BATCH_NOT_EXECUTABLE)

        now = validate_success(api.get_batch(batch["id"], ANALYST))
        assert now["status"] == "VALIDATED"

    def test_draft_batch_schedule_and_reopen_rejected(self, api):
        """PRD §3.5: "Scheduling moves `VALIDATED` to `SCHEDULED`
        (`ERR_BATCH_NOT_EXECUTABLE` otherwise) with a `scheduled_effective_date`
        that must not precede the logical clock date
        (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`); the batch's `version` increments."
        PRD §3.5: "A failed batch is not terminal: reopening moves
        `VALIDATION_FAILED` back to `DRAFT` (`ERR_BATCH_NOT_REOPENABLE` from any
        other state), resets every line to `PENDING`, clears every `error_id` so
        the next submit re-validates from scratch, and increments the batch's
        `version`."

        Design: Corner/state_machines/draft_batch_schedule_and_reopen_rejected
        """
        env = setup_worker_with_field(
            worker_number="W747", field_key="assignment.location_code", channels=[],
        )
        batch = create_batch_record(name="draft-guards")
        add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "SF")

        err1 = api.schedule_batch(
            batch["id"], {"scheduled_effective_date": "2026-08-15"}, ANALYST
        )
        validate_error(err1, ApiErrorId.ERR_BATCH_NOT_EXECUTABLE)

        err2 = api.reopen_batch(batch["id"], ANALYST)
        validate_error(err2, ApiErrorId.ERR_BATCH_NOT_REOPENABLE)

    def test_rollback_completed_batch_rejected(self, api):
        """PRD §3.5: "Rollback compensates a `COMPLETED_WITH_ERRORS` batch — from
        any other state it fails with `ERR_BATCH_NOT_ROLLBACKABLE`."

        Design: Corner/state_machines/rollback_completed_batch_rejected
        """
        env = setup_worker_with_field(
            worker_number="W748", field_key="assignment.location_code", channels=[],
        )
        batch, _ = create_scheduled_batch(
            [(env["worker"]["id"], env["field"]["id"], "SF")], name="no-rollback",
        )
        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED"

        err = api.rollback_batch(batch["id"], ANALYST)
        validate_error(err, ApiErrorId.ERR_BATCH_NOT_ROLLBACKABLE)

    def test_schedule_batch_with_past_date_rejected(self, api):
        """PRD §3.5: "Scheduling moves `VALIDATED` to `SCHEDULED`
        (`ERR_BATCH_NOT_EXECUTABLE` otherwise) with a `scheduled_effective_date`
        that must not precede the logical clock date
        (`ERR_EFFECTIVE_DATE_OUT_OF_WINDOW`); the batch's `version` increments."

        Design: Corner/state_machines/schedule_batch_with_past_date_rejected
        """
        env = setup_worker_with_field(
            worker_number="W749", field_key="assignment.location_code", channels=[],
        )
        batch = create_batch_record(name="past-schedule")
        add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "SF")
        submitted = submit_batch_record(batch["id"])
        assert submitted["status"] == "VALIDATED"

        err = api.schedule_batch(
            batch["id"], {"scheduled_effective_date": "2026-07-01"}, ANALYST
        )
        validate_error(err, ApiErrorId.ERR_EFFECTIVE_DATE_OUT_OF_WINDOW)


class TestBatchValidationCycle:
    def test_batch_validation_failure_reopen_cycle(self, api):
        """PRD §3.5: "With zero failed lines the batch becomes `VALIDATED`; with
        at least one it becomes `VALIDATION_FAILED`, the per-line outcomes
        standing as recorded. Either way the batch's `version` increments by one.
        A failed batch is not terminal: reopening moves `VALIDATION_FAILED` back
        to `DRAFT` (`ERR_BATCH_NOT_REOPENABLE` from any other state), resets every
        line to `PENDING`, clears every `error_id` so the next submit re-validates
        from scratch, and increments the batch's `version`."

        Design: Difficulty/non_linear_state_machine/batch_validation_failure_reopen_cycle
        """
        env = setup_worker_with_field(
            worker_number="W805", field_key="assignment.location_code", channels=[],
        )
        draft_field = create_data_field_record(
            field_key="assignment.pay_grade", sensitivity="INTERNAL", channels=[], activate=False,
        )
        batch = create_batch_record(name="reorg-cycle")
        add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "SF",
                              line_index=1)
        add_batch_line_record(batch["id"], env["worker"]["id"], draft_field["id"], "G7",
                              line_index=2)

        first = submit_batch_record(batch["id"])
        assert first["status"] == "VALIDATION_FAILED"

        reopened = validate_success(api.reopen_batch(batch["id"], ANALYST))
        assert reopened["status"] == "DRAFT"

        validate_success(api.activate_data_field(draft_field["id"], TEST_USERS["steward_headers"]))

        second = submit_batch_record(batch["id"])
        assert second["status"] == "VALIDATED"

        resp = api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})
        from test_helpers import get_success_data
        lines = sorted(get_success_data(resp), key=lambda line: line["line_index"])
        assert [line["status"] for line in lines] == ["VALIDATED", "VALIDATED"]

    def test_batch_reopen_resets_failed_lines_full_cycle(self, api):
        """PRD §3.5: "A failed batch is not terminal: reopening moves
        `VALIDATION_FAILED` back to `DRAFT` (`ERR_BATCH_NOT_REOPENABLE` from any
        other state), resets every line to `PENDING`, clears every `error_id` so
        the next submit re-validates from scratch, and increments the batch's
        `version`."

        Design: Difficulty/non_linear_state_machine/batch_validation_failure_reopen_cycle
        """
        env = setup_worker_with_field(
            worker_number="W806", field_key="assignment.location_code", channels=[],
        )
        draft_field = create_data_field_record(
            field_key="assignment.pay_grade", sensitivity="INTERNAL", channels=[], activate=False,
        )
        batch = create_batch_record(name="reorg-cycle-2")
        line1 = add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "SF",
                                      line_index=1)
        line2 = add_batch_line_record(batch["id"], env["worker"]["id"], draft_field["id"], "G7",
                                      line_index=2)

        first = submit_batch_record(batch["id"])
        assert first["status"] == "VALIDATION_FAILED"

        # The line reset is observable immediately after reopen.
        reopened = validate_success(api.reopen_batch(batch["id"], ANALYST))
        assert reopened["status"] == "DRAFT"
        from test_helpers import get_success_data
        resp = api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})
        lines = sorted(get_success_data(resp), key=lambda line: line["line_index"])
        assert [line["status"] for line in lines] == ["PENDING", "PENDING"]
        assert all(line["error_id"] is None for line in lines), "reopen clears every error_id"

        validate_success(api.activate_data_field(draft_field["id"], TEST_USERS["steward_headers"]))
        second = submit_batch_record(batch["id"])
        assert second["status"] == "VALIDATED"


class TestBatchLineValidation:
    def test_restricted_field_line_fails_batch_validation(self, api):
        """PRD §3.5: "Two restrictions apply at the line level: `RESTRICTED`
        fields are forbidden in batches — dual approval must not be bypassable
        through mass change, and a line referencing one fails with
        `ERR_RESTRICTED_FIELD_IN_BATCH` — and lines always apply with `NEW_RECORD`
        semantics regardless of any `correction_mode` supplied on the line."
        PRD §3.5: "With zero failed lines the batch becomes `VALIDATED`; with at
        least one it becomes `VALIDATION_FAILED`, the per-line outcomes standing
        as recorded."

        Design: Corner/state_machines/restricted_field_line_fails_batch_validation
        """
        env = setup_worker_with_field(
            worker_number="W750", sensitivity="RESTRICTED", channels=[],
        )
        batch = create_batch_record(name="restricted-line")
        add_batch_line_record(batch["id"], env["worker"]["id"], env["field"]["id"], "12000")

        submitted = submit_batch_record(batch["id"])
        assert submitted["status"] == "VALIDATION_FAILED"

        from test_helpers import get_success_data
        resp = api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})
        lines = get_success_data(resp)
        assert len(lines) == 1
        assert lines[0]["status"] == "FAILED"
        assert lines[0]["error_id"] == "ERR_RESTRICTED_FIELD_IN_BATCH"


class TestBatchExecute:
    def test_batch_execute_cascade_depth3(self, api):
        """PRD §3.5: "Execution requires `SCHEDULED` (`ERR_BATCH_NOT_EXECUTABLE`)
        and re-validates every line as it applies them sequentially in
        `line_index` ascending, ties broken by earliest creation — state drift
        between submit and execute, such as a worker terminated or a field
        deprecated in between, surfaces here as a `VALIDATED` line falling to
        `FAILED`. Each applied line runs the same truncation-and-insert machinery
        as a single `NEW_RECORD` apply, writes an audit entry with action
        `BATCH_APPLY` per sensitive line, emits per-channel integration events
        stamped with the batch's `batch_id`, and opens exception records for
        `WARNING` quality failures with `batch_id` set."

        Design: Difficulty/transitive_cascade/batch_execute_cascade_depth3
        """
        env = setup_worker_with_field(
            worker_number="W807", field_key="assignment.location_code",
            channels=["PAYROLL", "IDENTITY"], initial_location_code="NY",
        )
        batch, _ = create_scheduled_batch(
            [(env["worker"]["id"], env["field"]["id"], "SF")], name="loc-move",
        )

        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED"
        assert executed["applied_lines"] == 1

        from test_helpers import get_success_data
        lines = get_success_data(api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]}))
        assert lines[0]["status"] == "APPLIED"

        rows = list_assignment_rows(env["worker"]["id"])
        assert len(rows) == 2
        assert rows[0]["effective_end_date"] == "2026-09-01"
        assert rows[1]["effective_start_date"] == "2026-09-01"
        assert rows[1]["location_code"] == "SF"
        assert rows[1]["row_status"] == "FUTURE"

        queued = [e for e in list_events(batch_id=batch["id"]) if e["status"] == "QUEUED"]
        assert len(queued) == 2
        assert {e["channel"] for e in queued} == {"PAYROLL", "IDENTITY"}
        assert all(e["batch_id"] == batch["id"] for e in queued)

    def test_batch_execute_cascade_line_then_rows_then_events(self, api):
        """PRD §3.5: "When every line has applied, the batch lands in `COMPLETED`;
        when at least one line failed, it lands in `COMPLETED_WITH_ERRORS`, and
        the partial application stands — bulk processing is best-effort, and
        applied lines keep their effects."
        PRD §3.5: "Each applied line runs the same truncation-and-insert machinery
        as a single `NEW_RECORD` apply, writes an audit entry with action
        `BATCH_APPLY` per sensitive line, emits per-channel integration events
        stamped with the batch's `batch_id`, and opens exception records for
        `WARNING` quality failures with `batch_id` set."

        Second view of the depth-3 execute cascade: line flips APPLIED, the
        covering row truncates, and both downstream channels queue events.

        Design: Difficulty/transitive_cascade/batch_execute_cascade_depth3
        """
        env = setup_worker_with_field(
            worker_number="W808", field_key="assignment.location_code",
            channels=["PAYROLL", "IDENTITY"], initial_location_code="NY",
        )
        batch, _ = create_scheduled_batch(
            [(env["worker"]["id"], env["field"]["id"], "SF")], name="loc-move-2",
        )
        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED"

        # Depth 1: the line itself moved VALIDATED -> APPLIED.
        from test_helpers import get_success_data
        line = get_success_data(
            api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})
        )[0]
        assert line["status"] == "APPLIED"

        # Depth 2: the worker's timeline was truncated + extended.
        rows = list_assignment_rows(env["worker"]["id"])
        assert rows[0]["effective_end_date"] == "2026-09-01"
        assert rows[1]["location_code"] == "SF"

        # Depth 3: one QUEUED event per downstream channel.
        queued = [e for e in list_events(batch_id=batch["id"]) if e["status"] == "QUEUED"]
        assert len(queued) == 2
        assert {e["event_type"] for e in queued} == {"CHANGE_APPLIED"}

    def test_batch_execute_revalidates_and_fails_terminated_worker_line(self, api):
        """PRD §3.5: "Execution requires `SCHEDULED` (`ERR_BATCH_NOT_EXECUTABLE`)
        and re-validates every line as it applies them sequentially in
        `line_index` ascending, ties broken by earliest creation — state drift
        between submit and execute, such as a worker terminated or a field
        deprecated in between, surfaces here as a `VALIDATED` line falling to
        `FAILED`."
        PRD §3.5: "When every line has applied, the batch lands in `COMPLETED`;
        when at least one line failed, it lands in `COMPLETED_WITH_ERRORS`, and
        the partial application stands — bulk processing is best-effort, and
        applied lines keep their effects."

        Design: Corner/state_machines/batch_execute_revalidates_and_fails_terminated_worker_line
        """
        pos = create_position_record()
        wa = create_worker_record(pos["id"], worker_number="W751", legal_name="WA")
        wb = create_worker_record(pos["id"], worker_number="W752", legal_name="WB")
        field = create_data_field_record(
            field_key="assignment.location_code", sensitivity="INTERNAL", channels=[],
        )
        batch, _ = create_scheduled_batch(
            [(wa["id"], field["id"], "SF"), (wb["id"], field["id"], "SF")], name="drift",
        )
        validate_success(
            api.terminate_worker(wb["id"], {"termination_date": "2026-08-10"}, ANALYST)
        )

        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED_WITH_ERRORS"
        assert executed["applied_lines"] == 1
        assert executed["failed_lines"] == 1

        from test_helpers import get_success_data
        lines = sorted(
            get_success_data(api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})),
            key=lambda line: line["line_index"],
        )
        assert lines[0]["status"] == "APPLIED"
        assert lines[1]["status"] == "FAILED"
        assert lines[1]["error_id"] == "ERR_WORKER_NOT_ACTIVE"

        rows_wa = list_assignment_rows(wa["id"])
        assert len(rows_wa) == 2, "the applied line's effects stand (best-effort bulk)"
        assert rows_wa[1]["effective_start_date"] == "2026-09-01"

    def test_clock_sweep_auto_executes_scheduled_batch(self, api):
        """PRD §2.5: "Each clock advance re-evaluates every time-driven rule in
        the system: assignment rows derive their `row_status` from the clock
        relative to their interval (`FUTURE` rows whose start has been reached
        become `ACTIVE`; rows whose end has been reached or passed become
        `HISTORY`; a future row whose entire interval has elapsed moves directly
        from `FUTURE` to `HISTORY`); approved grants whose window has opened
        become `PROVISIONED` and grants whose window has closed become `EXPIRED`;
        waived exceptions whose waiver has lapsed reopen; scheduled batches whose
        effective date has been reached execute automatically; approved
        position-targeted change requests apply once the clock reaches their
        `effective_date`; and every exception record's `priority_score` is
        recomputed because age grows with the clock."

        Design: Corner/state_machines/clock_sweep_auto_executes_scheduled_batch
        """
        env = setup_worker_with_field(
            worker_number="W755", field_key="assignment.location_code", channels=[],
        )
        batch, _ = create_scheduled_batch(
            [(env["worker"]["id"], env["field"]["id"], "SF")],
            name="auto-exec", scheduled_effective_date="2026-08-15",
        )

        advance_clock("2026-08-15T00:00:00Z")

        now = validate_success(api.get_batch(batch["id"], ANALYST))
        assert now["status"] == "COMPLETED"
        assert now["applied_lines"] == 1


class TestBatchRollback:
    def test_batch_rollback_compensates_applied_lines(self, api):
        """PRD §3.5: "Each applied line is compensated in reverse `line_index`
        order: the inserted rows are `VOIDED`, truncated rows have their ends
        restored, an audit entry with action `BATCH_VOID` is written per line,
        and `REVERSAL` events are emitted for every channel that received one.
        Batch-originated events still sitting `QUEUED` move to `CANCELLED`. Lines
        move from `APPLIED` to `ROLLED_BACK` while failed lines are untouched,
        `applied_lines` recomputes to zero, and the batch's `version` increments
        by one as it settles in `ROLLED_BACK`."

        Design: Corner/state_machines/batch_rollback_compensates_applied_lines
        """
        pos = create_position_record()
        wa = create_worker_record(pos["id"], worker_number="W753", legal_name="WA")
        wb = create_worker_record(pos["id"], worker_number="W754", legal_name="WB")
        field = create_data_field_record(
            field_key="assignment.location_code", sensitivity="INTERNAL", channels=["PAYROLL"],
        )
        batch, _ = create_scheduled_batch(
            [(wa["id"], field["id"], "SF"), (wb["id"], field["id"], "SF")],
            name="rollback-me",
        )
        validate_success(
            api.terminate_worker(wb["id"], {"termination_date": "2026-08-10"}, ANALYST)
        )
        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED_WITH_ERRORS"

        rolled = validate_success(api.rollback_batch(batch["id"], ANALYST))
        assert rolled["status"] == "ROLLED_BACK"
        assert rolled["applied_lines"] == 0

        from test_helpers import get_success_data
        lines = sorted(
            get_success_data(api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})),
            key=lambda line: line["line_index"],
        )
        assert lines[0]["status"] == "ROLLED_BACK"
        assert lines[1]["status"] == "FAILED"

        rows_wa = list_assignment_rows(wa["id"])
        assert len(rows_wa) == 2
        assert rows_wa[0]["effective_end_date"] is None
        assert rows_wa[1]["row_status"] == "VOIDED"

        events = list_events(batch_id=batch["id"])
        cancelled = [e for e in events if e["status"] == "CANCELLED"]
        queued_reversals = [
            e for e in events if e["status"] == "QUEUED" and e["event_type"] == "REVERSAL"
        ]
        assert len(cancelled) == 1
        assert cancelled[0]["event_type"] == "CHANGE_APPLIED"
        assert len(queued_reversals) == 1


class TestBatchTotals:
    def test_batch_comp_adjust_per_line_rounding(self, api):
        """PRD §3.5: "Rounding order is pinned: each line is rounded to integer
        cents individually, and only then are the per-line deltas summed into
        `total_delta_cents` — summing first and rounding once is forbidden because
        the orders diverge. Two workers each earning 10010 cents and raised by 2.5
        percent resolve to 10260 cents apiece, 250 cents of delta each, 500 cents
        in total; the forbidden sum-then-round order would report 501."

        Design: Difficulty/combinatorial_formula/batch_comp_adjust_per_line_rounding
        """
        pos = create_position_record(headcount_budget=9)
        wa = create_worker_record(pos["id"], worker_number="W810", salary=10010, legal_name="WA")
        wb = create_worker_record(pos["id"], worker_number="W811", salary=10010, legal_name="WB")
        field = create_data_field_record(sensitivity="INTERNAL", channels=[])
        batch, _ = create_scheduled_batch(
            [
                (wa["id"], field["id"], "+2.5%"),
                (wb["id"], field["id"], "+2.5%"),
            ],
            name="reorg-2026",
        )

        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED"
        assert executed["total_delta_cents"] == 500

        rows_wa = [r for r in list_assignment_rows(wa["id"]) if r["row_status"] == "FUTURE"]
        assert len(rows_wa) == 1
        assert rows_wa[0]["salary_cents"] == 10260

    def test_batch_comp_adjust_per_line_rounding_line_deltas(self, api):
        """PRD §3.5: "For each applied line targeting `assignment.salary_cents`,
        the system resolves the new salary from the line's `new_value`: in `+P%`
        form, the prior salary is increased by P percent and the result rounded
        half-up to whole cents; in absolute form, the value is parsed as an
        integer. The prior salary is the salary of the worker's row covering the
        line's `effective_date` as it stood before this batch's execution. The
        line's `resolved_delta_cents` is the resolved new salary minus that prior
        salary, and it is null for non-salary lines."

        Design: Difficulty/combinatorial_formula/batch_comp_adjust_per_line_rounding
        """
        pos = create_position_record(headcount_budget=9)
        wa = create_worker_record(pos["id"], worker_number="W812", salary=10010, legal_name="WA")
        wb = create_worker_record(pos["id"], worker_number="W813", salary=10010, legal_name="WB")
        field = create_data_field_record(sensitivity="INTERNAL", channels=[])
        batch, _ = create_scheduled_batch(
            [
                (wa["id"], field["id"], "+2.5%"),
                (wb["id"], field["id"], "+2.5%"),
            ],
            name="reorg-2026-b",
        )

        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED"
        assert executed["total_delta_cents"] == 500

        from test_helpers import get_success_data
        lines = sorted(
            get_success_data(api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})),
            key=lambda line: line["line_index"],
        )
        assert [line["resolved_delta_cents"] for line in lines] == [250, 250]

        rows_wb = [r for r in list_assignment_rows(wb["id"]) if r["row_status"] == "FUTURE"]
        assert rows_wb[0]["salary_cents"] == 10260

    def test_batch_absolute_salary_delta_and_null_non_salary_delta(self, api):
        """PRD §3.5: "For each applied line targeting `assignment.salary_cents`,
        the system resolves the new salary from the line's `new_value`: in `+P%`
        form, the prior salary is increased by P percent and the result rounded
        half-up to whole cents; in absolute form, the value is parsed as an
        integer. The prior salary is the salary of the worker's row covering the
        line's `effective_date` as it stood before this batch's execution. The
        line's `resolved_delta_cents` is the resolved new salary minus that prior
        salary, and it is null for non-salary lines."

        Design: Corner/calculations/batch_absolute_salary_delta_and_null_non_salary_delta
        """
        pos = create_position_record()
        worker = create_worker_record(
            pos["id"], worker_number="W814", initial_location_code="NY",
        )
        sal_field = create_data_field_record(
            field_key="assignment.salary_cents", sensitivity="INTERNAL", channels=[],
        )
        loc_field = create_data_field_record(
            field_key="assignment.location_code", sensitivity="INTERNAL", channels=[],
        )
        batch, _ = create_scheduled_batch(
            [
                (worker["id"], sal_field["id"], "12000", "2026-09-01"),
                (worker["id"], loc_field["id"], "SF", "2026-10-01"),
            ],
            name="abs-delta",
        )

        executed = execute_batch_record(batch["id"])
        assert executed["status"] == "COMPLETED"
        assert executed["total_delta_cents"] == 2000

        from test_helpers import get_success_data
        lines = sorted(
            get_success_data(api.list_all_batch_lines(ANALYST, params={"batch_id": batch["id"]})),
            key=lambda line: line["line_index"],
        )
        assert lines[0]["resolved_delta_cents"] == 2000
        assert lines[1]["resolved_delta_cents"] is None
