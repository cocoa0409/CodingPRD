"""Work assignments and daily work logs: worker-state gating, petition-order
matching, live-assignment uniqueness, work-log windows/immutability, the
never-started escape hatch, and abandonment's enforcement side effects."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_work_log,
    create_assignment,
    create_work_log,
    end_assignment,
    get_reconciliation,
    get_success_data,
    set_clock,
    setup_active_order_pipeline,
    setup_two_grower_scenario,
    start_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]


class TestWorkerStateGate:
    def _order_with_one_visa_issued_one_petitioned(self, api):
        return setup_active_order_pipeline(
            passports=("P0001", "P0002"),
            requested_worker_count=2,
            visa_passports=("P0001",),
            start_assignments=False,
        )

    def test_assignment_create_requires_worker_visa_issued(self, api):
        """PRD 3.6: "The worker must be `VISA_ISSUED` (else
        `ERR_WORKER_INVALID_STATE`) and must have been petitioned to this very job
        order — the job order of the worker's petition must equal the order being
        assigned, otherwise `ERR_WORKER_ORDER_MISMATCH`; transfer-created
        assignments are the lone exemption from this petition-matching rule."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_worker_visa_issued
        """
        s = self._order_with_one_visa_issued_one_petitioned(api)
        petitioned = s["workers"]["P0002"]
        assert petitioned["status"] == "PETITIONED"

        resp = api.create_worker_assignment(
            {"worker_id": petitioned["id"], "job_order_id": s["order"]["id"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_INVALID_STATE)

    def test_assignment_create_control_visa_issued_succeeds(self, api):
        """PRD 3.6: "Placing a worker onto an order creates a worker assignment
        from a payload carrying `worker_id` and `job_order_id`. The order must be
        `ACTIVE` (else `ERR_JOB_ORDER_INVALID_STATE`) and its grower must be
        `ACTIVE` (else `ERR_GROWER_NOT_ACTIVE`). The worker must be `VISA_ISSUED`
        (else `ERR_WORKER_INVALID_STATE`)"
        PRD 3.6: "A new assignment starts in `PLANNED` status with `started_on`,
        `ended_on`, and `end_reason` all null; its read-only `guarantee_eligible`
        flag reads true for as long as the assignment is non-terminal."

        Design: Difficulty/cross_entity_state_dependency/assignment_create_requires_worker_visa_issued
        """
        s = self._order_with_one_visa_issued_one_petitioned(api)
        visa_issued = s["workers"]["P0001"]
        assert visa_issued["status"] == "VISA_ISSUED"

        created = validate_success(
            api.create_worker_assignment(
                {"worker_id": visa_issued["id"], "job_order_id": s["order"]["id"]}, ADMIN
            ),
            201,
        )
        assert created["status"] == "PLANNED"
        assert created["started_on"] is None
        assert created["guarantee_eligible"] is True


class TestWorkLogSurface:
    def test_work_log_immutable_unique_per_assignment_day(self, api):
        """PRD 3.6: "Work logs are the payroll ledger's raw entries: one immutable
        row per assignment per day, recorded by a `ContractorAdmin` with the
        `worker_assignment_id`, the `work_date`, the `hours_worked`, and the
        `units_picked`."
        PRD 3.6: "a second row for the same assignment and date is rejected with
        `ERR_DUPLICATE_WORK_LOG`"
        PRD 2.5: "Two record types are immutable after creation: a housing
        inspection and a work log are append-only ledger entries. Both carry only
        `id` and `created_at`; `updated_at` and `version` are absent from them
        entirely, because neither resource can ever be modified once recorded."

        Design: Corner/entities/work_log_immutable_unique_per_assignment_day
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        asg = s["assignments"]["P0001"]
        first = create_work_log(asg["id"], "2026-09-01", 8, 25)
        assert_work_log(first)

        resp = api.create_work_log(
            {"worker_assignment_id": asg["id"], "work_date": "2026-09-01",
             "hours_worked": 4, "units_picked": 10},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WORK_LOG)

        rows, meta = validate_paginated(api.list_work_logs(asg["id"], ADMIN))
        assert meta["total_count"] == 1
        assert rows[0]["hours_worked"] == 8, "first write is retained; the ledger is immutable"
        assert_work_log(rows[0])

    def test_assignment_and_worklog_guard_battery_rejected(self, api):
        """PRD 3.6: "One worker holds at most one live assignment: a worker who
        already has a `PLANNED` or `ACTIVE` assignment anywhere is rejected with
        `ERR_WORKER_ALREADY_ASSIGNED`."
        PRD 3.6: "A `PLANNED` assignment that never started may still need
        clearing: ending it accepts only `FOR_CAUSE` (any other reason is rejected
        with `ERR_INVALID_REQUEST`), moves it to `TERMINATED` with `ended_on` set
        to the clock date and `guarantee_eligible` false, and leaves the worker
        untouched — still `VISA_ISSUED`, never having started."
        PRD 3.6: "The `work_date` must lie inside the window from the assignment's
        `started_on` through the earlier of the clock date and the order's
        `work_end_date`, both bounds included; anything outside is rejected with
        `ERR_WORK_LOG_DATE_OUT_OF_RANGE`"
        PRD 3.6: "`hours_worked` must be a multiple of one quarter hour, strictly
        greater than zero, and at most sixteen hours (else `ERR_INVALID_HOURS`)."
        PRD 3.7: "Finalizing — allowed only when the parent assignment has reached
        `COMPLETED`, `TERMINATED`, or `TRANSFERRED_OUT` and the row is still
        `OPEN`, with any other combination rejected as
        `ERR_RECONCILIATION_INVALID_STATE`"

        Design: Corner/errors/assignment_and_worklog_guard_battery_rejected
        """
        s = setup_active_order_pipeline(
            passports=("P0001", "P0002"), requested_worker_count=2, start_assignments=False
        )
        jo_id = s["order"]["id"]
        wa, wb = s["workers"]["P0001"], s["workers"]["P0002"]
        asg_a = create_assignment(wa["id"], jo_id)  # PLANNED, never started
        asg_b = start_assignment(create_assignment(wb["id"], jo_id)["id"])  # ACTIVE
        set_clock("2026-09-05T00:00:00Z")

        # W_A already holds a PLANNED assignment.
        resp = api.create_worker_assignment({"worker_id": wa["id"], "job_order_id": jo_id}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_WORKER_ALREADY_ASSIGNED)

        # From PLANNED only FOR_CAUSE is accepted.
        resp = api.end_worker_assignment(asg_a["id"], {"end_reason": "COMPLETED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # Work date after the clock date is outside the allowed window.
        resp = api.create_work_log(
            {"worker_assignment_id": asg_b["id"], "work_date": "2026-09-06",
             "hours_worked": 8, "units_picked": 25},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WORK_LOG_DATE_OUT_OF_RANGE)

        # 8.3 hours is not a multiple of 0.25.
        resp = api.create_work_log(
            {"worker_assignment_id": asg_b["id"], "work_date": "2026-09-05",
             "hours_worked": 8.3, "units_picked": 25},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_HOURS)

        # The reconciliation cannot be finalized while the assignment is ACTIVE.
        resp = api.finalize_reconciliation(asg_b["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_INVALID_STATE)

    def test_start_after_order_period_end_rejected(self, api):
        """PRD 3.6: "Starting work is allowed only from `PLANNED` (else
        `ERR_ASSIGNMENT_INVALID_STATE`) and only while the clock date has not
        passed the order's `work_end_date` (else `ERR_ORDER_PERIOD_ENDED`)."
        PRD 3.6: "A `PLANNED` assignment that never started may still need
        clearing: ending it accepts only `FOR_CAUSE` (any other reason is rejected
        with `ERR_INVALID_REQUEST`), moves it to `TERMINATED` with `ended_on` set
        to the clock date and `guarantee_eligible` false, and leaves the worker
        untouched — still `VISA_ISSUED`, never having started. This escape hatch
        exists so a never-started assignment cannot block contract close-out."

        Design: Corner/errors/start_after_order_period_end_rejected
        """
        s = setup_active_order_pipeline(passports=("P0001",), start_assignments=False)
        asg = create_assignment(s["workers"]["P0001"]["id"], s["order"]["id"])
        assert asg["status"] == "PLANNED"

        set_clock("2026-10-21T00:00:00Z")
        resp = api.start_worker_assignment(asg["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_PERIOD_ENDED)

        ended = end_assignment(asg["id"], "FOR_CAUSE")
        assert ended["status"] == "TERMINATED"
        assert ended["end_reason"] == "FOR_CAUSE"
        assert ended["guarantee_eligible"] is False
        worker = get_success_data(api.get_worker(s["workers"]["P0001"]["id"], ADMIN))
        assert worker["status"] == "VISA_ISSUED", "never-started worker is untouched"

    def test_assignment_to_unrelated_order_rejected(self, api):
        """PRD 3.6: "The worker must be `VISA_ISSUED` (else
        `ERR_WORKER_INVALID_STATE`) and must have been petitioned to this very job
        order — the job order of the worker's petition must equal the order being
        assigned, otherwise `ERR_WORKER_ORDER_MISMATCH`; transfer-created
        assignments are the lone exemption from this petition-matching rule."

        Design: Corner/errors/assignment_to_unrelated_order_rejected
        """
        s = setup_two_grower_scenario(start_j1_assignment=False)
        wa = s["wa"]
        assert wa["status"] == "VISA_ISSUED"

        resp = api.create_worker_assignment(
            {"worker_id": wa["id"], "job_order_id": s["jo2"]["id"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_WORKER_ORDER_MISMATCH)

        rows, meta = validate_paginated(api.list_worker_assignments(ADMIN, params={"worker_id": wa["id"]}))
        assert meta["total_count"] == 0 and rows == []


class TestAbandonment:
    def test_abandonment_auto_audit_and_guarantee_forfeiture(self, api):
        """PRD 3.6: "Reporting abandonment moves the assignment to `TERMINATED`
        with `end_reason` `ABANDONED` and `guarantee_eligible` false, moves the
        worker from `WORKING` to `ABANDONED`, vacates housing exactly as a normal
        ending does, recomputes the reconciliation, and — critically — causes the
        system to open an audit case automatically: the case names the order's
        grower, is scoped to the order, carries `trigger_source` `ABANDONMENT`,
        and opens in `OPEN` status."
        PRD 3.7: "Whether the guarantee applies is carried by `guarantee_applied`:
        it is false only for a `FINALIZED` reconciliation whose assignment ended
        with `end_reason` `FOR_CAUSE` or `ABANDONED`, and true in every other case
        — while the row is `OPEN`, the provisional computation simply assumes
        eligibility."
        PRD 3.7: "`guarantee_pay_cents` prices the shortfall at the hourly floor —
        the shortfall quarter-hours multiplied by `required_hourly_floor_cents`
        and divided by four, rounded half-up to a whole cent — and is payable only
        when the guarantee applies; otherwise it is zero."

        Design: Corner/state_machines/abandonment_auto_audit_and_guarantee_forfeiture
        """
        s = setup_active_order_pipeline(passports=("P0001",))
        asg = s["assignments"]["P0001"]
        create_work_log(asg["id"], "2026-09-01", 8, 25)
        set_clock("2026-09-05T00:00:00Z")

        reported = validate_success(api.report_abandonment(asg["id"], {}, ADMIN), 200)
        assert reported["status"] == "TERMINATED"
        assert reported["end_reason"] == "ABANDONED"
        assert reported["ended_on"] == "2026-09-05"
        assert reported["guarantee_eligible"] is False
        assert get_success_data(api.get_worker(s["workers"]["P0001"]["id"], ADMIN))["status"] == "ABANDONED"

        cases, meta = validate_paginated(
            api.list_audit_cases(TEST_USERS["wage_auditor_headers"], params={"grower_id": s["grower"]["id"]})
        )
        assert meta["total_count"] == 1
        assert cases[0]["trigger_source"] == "ABANDONMENT"
        assert cases[0]["status"] == "OPEN"
        assert cases[0]["job_order_id"] == s["order"]["id"]

        rec = validate_success(api.finalize_reconciliation(asg["id"], ADMIN), 200)
        assert rec["status"] == "FINALIZED"
        assert rec["guarantee_applied"] is False
        # Basis 2026-09-01..2026-09-05 = 5 workdays x 32 quarter-hours = 160;
        # floor(160 * 3/4) = 120 guaranteed; worked 32 -> shortfall 88.
        assert rec["guarantee_basis_workdays"] == 5
        assert rec["guaranteed_quarters"] == 120
        assert rec["worked_quarters"] == 32
        assert rec["shortfall_quarters"] == 88
        assert rec["guarantee_pay_cents"] == 0, "guarantee forfeited by ABANDONED end reason"
        assert rec["piece_earnings_cents"] == 11250  # 25 units x 450
        assert rec["makeup_pay_cents"] == 3550  # max(0, 14800 floor - 11250 piece)
        assert rec["inbound_transport_owed_cents"] == 0  # ended before the 50% threshold
        assert rec["outbound_transport_owed_cents"] == 0
        assert rec["total_due_cents"] == 14800
