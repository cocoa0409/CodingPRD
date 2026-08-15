"""Timesheet lifecycle, overlap semantics, approval cascade, and listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    approve_timesheet,
    create_approved_timesheet,
    create_pay_run,
    create_timesheet,
    get_timesheet,
    get_worker,
    make_household_client_headers,
    make_payroll_admin_headers,
    make_worker_headers,
    make_work_entries,
    setup_active_worker,
    setup_calculated_pay_run,
    setup_classified_worker,
    submit_timesheet,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTimesheetRejectResubmitCycle:
    def _setup_submitted_timesheet(self, api):
        employer, worker, _a = setup_active_worker("AA")
        ts = create_timesheet(
            worker["id"], "2026-02-02", "2026-02-09",
            [{"work_date": "2026-02-02", "worked_minutes": 480}],
        )
        submit_timesheet(worker["id"], ts["id"])
        return employer, worker, ts

    def test_reject_returns_to_draft_and_resubmit_restores_submitted(self, api):
        """PRD §3.5: "A `HouseholdClient` may reject a `SUBMITTED` timesheet, returning it to `DRAFT` with no other side effects; or may approve it."
        PRD §3.5: "The `Worker` submits it, transitioning `DRAFT → SUBMITTED` and stamping `submitted_at` with the logical clock's current instant; submission requires `total_worked_minutes` to be strictly greater than 0 (otherwise `ERR_INVALID_REQUEST`)."

        Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_cycle
        """
        employer, worker, ts = self._setup_submitted_timesheet(api)

        resp = api.reject_timesheet(ts["id"], make_household_client_headers(employer["id"]))
        assert validate_success(resp, 200)["status"] == "DRAFT"

        resp = api.submit_timesheet(ts["id"], make_worker_headers(worker["id"]))
        assert validate_success(resp, 200)["status"] == "SUBMITTED"

    def test_approve_after_cycle_and_reject_from_approved_fails(self, api):
        """PRD §3.5: "When approval succeeds, three cascades fire in the same request. First, the worker's `ytd_approved_minutes` increases by `total_worked_minutes` and `accrued_leave_minutes` is recomputed (see §3.7)."
        PRD §2.8: "**State-machine preconditions** — the target transition's `from`-state and any parent-status gates; failure yields `ERR_INVALID_STATE`, with the pay-run-finalize staleness gate surfacing as `ERR_PAYRUN_STALE`."

        Design: Difficulty/non_linear_state_machine/timesheet_reject_resubmit_cycle
        """
        employer, worker, ts = self._setup_submitted_timesheet(api)
        approve_timesheet(employer["id"], ts["id"])

        after = get_timesheet(ts["id"])
        assert after["status"] == "APPROVED"
        worker_after = get_worker(worker["id"])
        assert worker_after["ytd_approved_minutes"] == 480

        resp = api.reject_timesheet(ts["id"], make_household_client_headers(employer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTimesheetSubmitGate:
    def test_submit_from_submitted_returns_invalid_state(self, api):
        """PRD §3.5: "The `Worker` submits it, transitioning `DRAFT → SUBMITTED` and stamping `submitted_at` with the logical clock's current instant; submission requires `total_worked_minutes` to be strictly greater than 0 (otherwise `ERR_INVALID_REQUEST`)."
        PRD §2.8: "**State-machine preconditions** — the target transition's `from`-state and any parent-status gates; failure yields `ERR_INVALID_STATE`, with the pay-run-finalize staleness gate surfacing as `ERR_PAYRUN_STALE`."

        Design: Corner/state_machines/timesheet_submit_from_submitted_returns_invalid_state
        """
        employer, worker, _a = setup_active_worker("AA")
        ts = create_timesheet(
            worker["id"], "2026-02-02", "2026-02-09",
            [{"work_date": "2026-02-02", "worked_minutes": 480}],
        )
        submit_timesheet(worker["id"], ts["id"])
        resp = api.submit_timesheet(ts["id"], make_worker_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTimesheetHalfOpenOverlap:
    def _setup_worker_with_first_timesheet(self, api):
        employer, worker, _a = setup_active_worker("AA")
        create_timesheet(
            worker["id"], "2026-01-05", "2026-01-12",
            [{"work_date": "2026-01-05", "worked_minutes": 480}],
        )
        return employer, worker

    def test_adjacent_period_start_equal_prior_end_is_allowed(self, api):
        """PRD §3.5: "The new timesheet's half-open interval must not overlap any other non-`LOCKED` timesheet of the same worker; adjacency (one's `period_end` equal to another's `period_start`) is allowed, but a true overlap is rejected with `ERR_TIMESHEET_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/timesheet_half_open_adjacency
        """
        _employer, worker = self._setup_worker_with_first_timesheet(api)
        resp = api.create_timesheet(
            worker["id"],
            {
                "period_start": "2026-01-12",
                "period_end": "2026-01-19",
                "entries": [{"work_date": "2026-01-12", "worked_minutes": 480}],
            },
            make_worker_headers(worker["id"]),
        )
        data = validate_success(resp, 201)
        assert data["period_start"] == "2026-01-12"
        assert data["status"] == "DRAFT"

    def test_overlapping_period_returns_409(self, api):
        """PRD §3.5: "The new timesheet's half-open interval must not overlap any other non-`LOCKED` timesheet of the same worker; adjacency (one's `period_end` equal to another's `period_start`) is allowed, but a true overlap is rejected with `ERR_TIMESHEET_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/timesheet_half_open_adjacency
        """
        _employer, worker = self._setup_worker_with_first_timesheet(api)
        resp = api.create_timesheet(
            worker["id"],
            {
                "period_start": "2026-01-11",
                "period_end": "2026-01-18",
                "entries": [{"work_date": "2026-01-11", "worked_minutes": 480}],
            },
            make_worker_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TIMESHEET_OVERLAP)


class TestTimesheetAgreementGate:
    def test_timesheet_without_covering_agreement_returns_422(self, api):
        """PRD §3.5: "Creating a timesheet requires the worker's `status` to be `CLASSIFIED` or `ACTIVE`, and requires an `ACTIVE` agreement whose `[effective_from, effective_to]` covers the timesheet's period — otherwise `ERR_NO_ACTIVE_AGREEMENT`."

        Design: Corner/validations/timesheet_create_without_covering_agreement_returns_422
        """
        employer, worker, _a = setup_classified_worker(
            "AA",
            worker_overrides={"hire_date": "2026-03-02"},
            agreement_overrides={"effective_from": "2026-03-01"},
        )
        resp = api.create_timesheet(
            worker["id"],
            {
                "period_start": "2026-02-02",
                "period_end": "2026-02-09",
                "entries": [{"work_date": "2026-02-02", "worked_minutes": 480}],
            },
            make_worker_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AGREEMENT)


class TestTimesheetApprovalCascade:
    def _setup_calculated_run_then_submitted_timesheet(self, api):
        """Pay run CALCULATED on the guarantee basis first; covering timesheet
        created and submitted afterwards so its approval stales the run."""
        employer, worker, _a = setup_active_worker(
            "AA", agreement_overrides={"guaranteed_minutes_per_week": 2400}
        )
        run = setup_calculated_pay_run(employer["id"])
        ts = create_timesheet(
            worker["id"], "2026-01-05", "2026-01-12",
            make_work_entries("2026-01-05", [540, 540, 540, 540, 540]),
        )
        submit_timesheet(worker["id"], ts["id"])
        return employer, worker, run, ts

    def test_approval_mutates_worker_and_stales_pay_run(self, api):
        """PRD §3.5: "When approval succeeds, three cascades fire in the same request. First, the worker's `ytd_approved_minutes` increases by `total_worked_minutes` and `accrued_leave_minutes` is recomputed (see §3.7). Second, every `PayRun` in `CALCULATED` status whose `[period_start, period_end)` covers this timesheet's period flips its `recalc_status` from `CURRENT` to `STALE`."

        Design: Difficulty/transitive_cascade/timesheet_approval_cascade_stales_payrun
        """
        employer, worker, run, ts = self._setup_calculated_run_then_submitted_timesheet(api)
        approve_timesheet(employer["id"], ts["id"])

        worker_after = get_worker(worker["id"])
        assert worker_after["ytd_approved_minutes"] == 2700
        assert worker_after["accrued_leave_minutes"] == 90

        resp = api.get_pay_run(run["id"], make_payroll_admin_headers())
        run_after = validate_success(resp, 200)
        assert run_after["recalc_status"] == "STALE", (
            f"covering CALCULATED pay run must flip to STALE, got {run_after['recalc_status']}"
        )

    def test_approval_stales_paycheck_and_finalize_refused(self, api):
        """PRD §3.5: "Third, each such `STALE` pay run's member paychecks that are still in `CALCULATED` status have `basis_stale` set to true. The stale markers are the serialization point that prevents a pay run from being finalized against timesheet data the run has not absorbed."
        PRD §3.6: "`recalc_status` must be `CURRENT` (else `ERR_PAYRUN_STALE`, HTTP 409);"

        Design: Difficulty/transitive_cascade/timesheet_approval_cascade_stales_payrun
        """
        employer, worker, run, ts = self._setup_calculated_run_then_submitted_timesheet(api)
        approve_timesheet(employer["id"], ts["id"])

        resp = api.list_pay_run_paychecks(run["id"], make_payroll_admin_headers())
        paychecks, _meta = validate_paginated(resp)
        assert len(paychecks) == 1
        assert paychecks[0]["basis"] == "GUARANTEE_FALLBACK"
        assert paychecks[0]["basis_stale"] is True

        resp = api.finalize_pay_run(run["id"], make_payroll_admin_headers())
        validate_error(resp, ApiErrorId.ERR_PAYRUN_STALE)


class TestTimesheetListing:
    def test_timesheet_list_pagination_envelope(self, api):
        """PRD §2.3: "All list endpoints accept two query parameters, `limit` and `offset`."
        PRD §2.3: "The `meta` envelope of every list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when further results exist beyond the current page."

        Design: Corner/endpoints/timesheet_list_pagination_envelope
        """
        employer, worker, _a = setup_active_worker("AA")
        create_timesheet(
            worker["id"], "2026-01-05", "2026-01-12",
            [{"work_date": "2026-01-05", "worked_minutes": 60}],
        )
        create_timesheet(
            worker["id"], "2026-01-12", "2026-01-19",
            [{"work_date": "2026-01-12", "worked_minutes": 60}],
        )

        resp = api.list_worker_timesheets(
            worker["id"], make_payroll_admin_headers(), params={"limit": 1, "offset": 0}
        )
        page1, meta1 = validate_paginated(resp)
        assert len(page1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert resp.json()["response_type"] == "array"

        resp = api.list_worker_timesheets(
            worker["id"], make_payroll_admin_headers(), params={"limit": 1, "offset": 1}
        )
        page2, meta2 = validate_paginated(resp)
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"]
