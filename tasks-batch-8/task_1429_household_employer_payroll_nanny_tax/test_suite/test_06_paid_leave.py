"""Paid leave: accrual floors, overlap semantics, balance gates, cancel restore."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_leave_request,
    cancel_leave_request,
    create_approved_timesheet,
    create_leave_request,
    deny_leave_request,
    get_worker,
    make_household_client_headers,
    make_worker_headers,
    make_work_entries,
    setup_active_worker,
    setup_worker_with_accrued_leave,
    validate_error,
    validate_success,
)


class TestLeaveAccrualFloor:
    def test_floor_boundary_29_then_30_approved_minutes(self, api):
        """PRD §3.7: "On every timesheet approval, the worker's `ytd_approved_minutes` — the sum of `total_worked_minutes` over `APPROVED` or `LOCKED` timesheets in the logical clock's calendar year — is incremented, and `accrued_leave_minutes` is recomputed as the smaller of: the integer floor of `ytd_approved_minutes` divided by 30 (one hour of leave earned per 30 hours worked, so the 29th worked minute of a 30-minute unit earns nothing), and the annual cap of 2400 minutes (40 hours)."

        Design: Corner/calculations/leave_accrual_floor_boundary
        """
        employer, worker, _a = setup_active_worker("AA")
        create_approved_timesheet(
            employer["id"], worker["id"], "2026-01-05", "2026-01-12",
            [{"work_date": "2026-01-05", "worked_minutes": 29}],
        )
        # floor(29 / 30) == 0: the 29th minute of a 30-minute unit earns nothing.
        assert get_worker(worker["id"])["accrued_leave_minutes"] == 0

        create_approved_timesheet(
            employer["id"], worker["id"], "2026-01-12", "2026-01-19",
            [{"work_date": "2026-01-12", "worked_minutes": 1}],
        )
        after = get_worker(worker["id"])
        assert after["ytd_approved_minutes"] == 30
        assert after["accrued_leave_minutes"] == 1


class TestLeaveClosedIntervalOverlap:
    def _setup_worker_with_first_leave(self, api):
        """180 accrued minutes; leave L1 [2026-03-02, 2026-03-03] APPROVED."""
        employer, worker = setup_worker_with_accrued_leave((2700, 2700))
        l1 = create_leave_request(worker["id"], "2026-03-02", "2026-03-03", 60)
        approve_leave_request(employer["id"], l1["id"])
        return employer, worker

    def test_back_to_back_closed_interval_is_allowed(self, api):
        """PRD §3.7: "The closed interval must not overlap any `REQUESTED` or `APPROVED` leave of the same worker; back-to-back intervals (another leave's `end_date` one day before this request's `start_date`) are allowed, but a true overlap is rejected with `ERR_LEAVE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/leave_closed_interval_adjacency
        """
        _e, worker = self._setup_worker_with_first_leave(api)
        resp = api.create_leave_request(
            worker["id"],
            {"start_date": "2026-03-04", "end_date": "2026-03-05", "requested_minutes": 60},
            make_worker_headers(worker["id"]),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "REQUESTED"
        assert data["start_date"] == "2026-03-04"

    def test_sharing_a_single_day_returns_409(self, api):
        """PRD §3.7: "The closed interval must not overlap any `REQUESTED` or `APPROVED` leave of the same worker; back-to-back intervals (another leave's `end_date` one day before this request's `start_date`) are allowed, but a true overlap is rejected with `ERR_LEAVE_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/leave_closed_interval_adjacency
        """
        _e, worker = self._setup_worker_with_first_leave(api)
        create_leave_request(worker["id"], "2026-03-04", "2026-03-05", 60)
        resp = api.create_leave_request(
            worker["id"],
            {"start_date": "2026-03-05", "end_date": "2026-03-06", "requested_minutes": 60},
            make_worker_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_LEAVE_OVERLAP)


class TestLeaveOverlapBeatsBalance:
    def _setup(self, api):
        """90 accrued minutes; L1 [2026-03-02, 2026-03-03] 90 minutes REQUESTED."""
        employer, worker = setup_worker_with_accrued_leave((2700,))
        create_leave_request(worker["id"], "2026-03-02", "2026-03-03", 90)
        return employer, worker

    def test_overlapping_and_insufficient_request_reports_overlap(self, api):
        """PRD §2.8: "**Business temporal** — overlap checks on timesheets, leave requests, and pay runs; the new-hire reporting window at worker activation; the quarter-closure rule on filing prepare; the not-in-the-future rule on deposit `remitted_on`. Failures yield `ERR_TIMESHEET_OVERLAP`, `ERR_LEAVE_OVERLAP`, `ERR_PAYRUN_OVERLAP`, `ERR_NEW_HIRE_REPORT_LATE`, `ERR_QUARTER_NOT_CLOSED`, or `ERR_INVALID_REQUEST` as appropriate."
        PRD §2.8: "**Business fiscal** — leave balance sufficiency, deposit amount against the safe-harbor requirement, year-end SSN completeness; failures yield `ERR_INSUFFICIENT_LEAVE_BALANCE`, `ERR_DEPOSIT_BELOW_REQUIRED`, or `ERR_MISSING_SSN`."

        Design: Difficulty/priority_pair_validation_conflict/leave_overlap_beats_balance
        """
        _e, worker = self._setup(api)
        # [03-03, 03-04] shares 03-03 with L1 AND 120 > 90 available: temporal wins.
        resp = api.create_leave_request(
            worker["id"],
            {"start_date": "2026-03-03", "end_date": "2026-03-04", "requested_minutes": 120},
            make_worker_headers(worker["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_LEAVE_OVERLAP)
        assert err["error_id"] != "ERR_INSUFFICIENT_LEAVE_BALANCE"

    def test_insufficient_balance_alone_reports_fiscal_error(self, api):
        """PRD §3.7: "The request requires the worker to be in `ACTIVE` status, and `requested_minutes` must not exceed `available_leave_minutes` — otherwise `ERR_INSUFFICIENT_LEAVE_BALANCE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/leave_overlap_beats_balance
        """
        _e, worker = self._setup(api)
        # Non-overlapping dates isolate the fiscal rule: 120 > 90 available.
        resp = api.create_leave_request(
            worker["id"],
            {"start_date": "2026-04-06", "end_date": "2026-04-07", "requested_minutes": 120},
            make_worker_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LEAVE_BALANCE)


class TestLeaveBalanceGate:
    def test_request_over_zero_balance_returns_422(self, api):
        """PRD §3.7: "The request requires the worker to be in `ACTIVE` status, and `requested_minutes` must not exceed `available_leave_minutes` — otherwise `ERR_INSUFFICIENT_LEAVE_BALANCE` (HTTP 422)."

        Design: Corner/validations/leave_request_over_zero_balance_returns_422
        """
        employer, worker, _a = setup_active_worker("AA")
        assert get_worker(worker["id"])["available_leave_minutes"] == 0
        resp = api.create_leave_request(
            worker["id"],
            {"start_date": "2026-03-02", "end_date": "2026-03-03", "requested_minutes": 30},
            make_worker_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LEAVE_BALANCE)


class TestLeaveApproveCancelRestoresBalance:
    def _setup(self, api):
        """90 accrued minutes; L1 [2026-03-02, 2026-03-03] 60 minutes REQUESTED."""
        employer, worker = setup_worker_with_accrued_leave((2700,))
        leave = create_leave_request(worker["id"], "2026-03-02", "2026-03-03", 60)
        return employer, worker, leave

    def test_approve_consumes_balance(self, api):
        """PRD §3.7: "A `HouseholdClient` approves a `REQUESTED` leave — the approval re-checks `available_leave_minutes` against `requested_minutes` and rejects with `ERR_INSUFFICIENT_LEAVE_BALANCE` if the balance has dropped since creation — incrementing `used_leave_minutes` by `requested_minutes` and recomputing `available_leave_minutes`."

        Design: Difficulty/compensating_invariant/leave_approve_cancel_restores_balance
        """
        employer, worker, leave = self._setup(api)
        approve_leave_request(employer["id"], leave["id"])
        after = get_worker(worker["id"])
        assert after["used_leave_minutes"] == 60
        assert after["available_leave_minutes"] == 30
        assert after["accrued_leave_minutes"] == 90

    def test_cancel_restores_balance_and_leaves_accrual_untouched(self, api):
        """PRD §3.7: "A `Worker` cancels their own leave from either `REQUESTED` or `APPROVED`; cancelling an `APPROVED` leave decrements `used_leave_minutes` by `requested_minutes` — `accrued_leave_minutes` is untouched and `available_leave_minutes` returns to its pre-approval value."

        Design: Difficulty/compensating_invariant/leave_approve_cancel_restores_balance
        """
        employer, worker, leave = self._setup(api)
        approve_leave_request(employer["id"], leave["id"])
        cancel_leave_request(worker["id"], leave["id"])
        after = get_worker(worker["id"])
        assert after["used_leave_minutes"] == 0
        assert after["available_leave_minutes"] == 90
        assert after["accrued_leave_minutes"] == 90, (
            "accrued leave is conserved: approve/cancel must never move it"
        )


class TestLeaveTerminalStates:
    def test_denied_and_cancelled_are_terminal(self, api):
        """PRD §3.7: "`DENIED` and `CANCELLED` are terminal."
        PRD §3.7: "A `HouseholdClient` may instead deny a `REQUESTED` leave, transitioning it to `DENIED` with no balance effects."

        Design: Corner/state_machines/leave_deny_terminal_and_cancel_lockdown
        """
        employer, worker = setup_worker_with_accrued_leave((2700,))
        l1 = create_leave_request(worker["id"], "2026-04-06", "2026-04-07", 30)
        l2 = create_leave_request(worker["id"], "2026-05-04", "2026-05-05", 30)
        deny_leave_request(employer["id"], l1["id"])
        cancel_leave_request(worker["id"], l2["id"])

        resp = api.cancel_leave_request(l1["id"], make_worker_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api.approve_leave_request(
            l2["id"], make_household_client_headers(employer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
