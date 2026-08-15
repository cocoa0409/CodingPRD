"""Worker classification, agreements, activation gating, and termination."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_worker,
    classify_worker,
    create_agreement,
    create_employer,
    create_registration,
    create_rule_pack,
    create_worker,
    get_worker,
    make_household_client_headers,
    make_payroll_admin_headers,
    make_worker_headers,
    setup_active_worker,
    setup_classified_worker,
    setup_registered_employer,
    terminate_worker,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClassification:
    def test_classification_score_three_yields_contractor(self, api):
        """PRD §3.4: "One point is awarded for each of the following answers: `controls_schedule` answered `WORKER`; `supplies_own_tools` answered `WORKER`; `hires_own_substitutes` answered `ALLOWED`; `paid_by` answered `PROJECT_NOT_HOURS`."
        PRD §3.4: "A score of at least 3 classifies the worker as `CONTRACTOR`; otherwise the worker is `EMPLOYEE`."

        Design: Corner/calculations/classification_score_threshold
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        w3 = create_worker(employer["id"], full_name="Three Score")
        w2 = create_worker(employer["id"], full_name="Two Score")
        client = make_household_client_headers(employer["id"])

        # Score 3: WORKER, EMPLOYER, ALLOWED, PROJECT_NOT_HOURS -> 1+0+1+1 = 3.
        resp = api.classify_worker(
            w3["id"],
            {"classification_answers": [
                {"question_key": "controls_schedule", "answer": "WORKER"},
                {"question_key": "supplies_own_tools", "answer": "EMPLOYER"},
                {"question_key": "hires_own_substitutes", "answer": "ALLOWED"},
                {"question_key": "paid_by", "answer": "PROJECT_NOT_HOURS"},
            ]},
            client,
        )
        data3 = validate_success(resp, 200)
        assert data3["classification"] == "CONTRACTOR"

        # Score 2: WORKER, WORKER, NOT_ALLOWED, HOURLY -> 1+1+0+0 = 2.
        resp = api.classify_worker(
            w2["id"],
            {"classification_answers": [
                {"question_key": "controls_schedule", "answer": "WORKER"},
                {"question_key": "supplies_own_tools", "answer": "WORKER"},
                {"question_key": "hires_own_substitutes", "answer": "NOT_ALLOWED"},
                {"question_key": "paid_by", "answer": "HOURLY"},
            ]},
            client,
        )
        data2 = validate_success(resp, 200)
        assert data2["classification"] == "EMPLOYEE"


class TestWorkerActivationGates:
    def test_contractor_cannot_be_activated_returns_422(self, api):
        """PRD §3.4: "The classification must be `EMPLOYEE` — a `CONTRACTOR` may not be put on payroll (else `ERR_CONTRACTOR_NOT_PAYABLE`, HTTP 422)."

        Design: Corner/validations/contractor_cannot_be_activated_returns_422
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        reg = create_registration(employer["id"], "AA", "NEW_HIRE_DIRECTORY")
        validate_success(api.submit_registration(reg["id"], make_payroll_admin_headers()), 200)
        validate_success(
            api.activate_registration(
                reg["id"], {"agency_account_number": "NH-001"}, make_payroll_admin_headers()
            ),
            200,
        )
        worker = create_worker(employer["id"], full_name="Con Tractor")
        classified = classify_worker(employer["id"], worker["id"], "CONTRACTOR")
        assert classified["classification"] == "CONTRACTOR"
        create_agreement(employer["id"], worker["id"])
        resp = api.activate_worker(
            worker["id"],
            {"new_hire_report_date": "2026-01-06"},
            make_household_client_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_PAYABLE)

    def test_new_hire_report_outside_window_returns_422(self, api):
        """PRD §3.4: "Finally, the new-hire reporting window is enforced: `new_hire_report_date` must fall on or after `hire_date`, must fall on or before `hire_date` plus the pack's `new_hire_report_days`, and must not lie after the logical-clock current date; a violation yields `ERR_NEW_HIRE_REPORT_LATE` (HTTP 422)."

        Design: Corner/validations/new_hire_report_late_returns_422
        """
        employer, worker, _agreement = setup_classified_worker("AA")
        # hire_date 2026-01-05 + 20-day window = 2026-01-25 latest; 2026-01-26 is late.
        resp = api.activate_worker(
            worker["id"],
            {"new_hire_report_date": "2026-01-26"},
            make_household_client_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NEW_HIRE_REPORT_LATE)
        assert get_worker(worker["id"])["status"] == "CLASSIFIED"

    def test_activate_without_active_new_hire_registration_returns_422(self, api):
        """PRD §3.4: "The employer must hold an `ACTIVE` `NEW_HIRE_DIRECTORY` registration for the worker's `work_state_code` (else `ERR_REGISTRATION_INACTIVE`)."

        Design: Corner/validations/worker_activate_without_active_registration_returns_422
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        # Registration stays DRAFT: never submitted or activated.
        create_registration(employer["id"], "AA", "NEW_HIRE_DIRECTORY")
        worker = create_worker(employer["id"], full_name="Reg Ina")
        classify_worker(employer["id"], worker["id"], "EMPLOYEE")
        create_agreement(employer["id"], worker["id"])
        resp = api.activate_worker(
            worker["id"],
            {"new_hire_report_date": "2026-01-06"},
            make_household_client_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_INACTIVE)


class TestAgreements:
    def test_agreement_below_state_minimum_wage_returns_422(self, api):
        """PRD §3.4: "The `hourly_rate_cents` must be at least the work-state pack's `min_wage_cents` (otherwise `ERR_BELOW_MIN_WAGE`, HTTP 422) and must divide evenly by 60 (otherwise `ERR_INVALID_REQUEST`)."

        Design: Corner/validations/agreement_below_min_wage_returns_422
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        worker = create_worker(employer["id"], full_name="Min W")
        classify_worker(employer["id"], worker["id"], "EMPLOYEE")
        resp = api.create_agreement(
            worker["id"],
            {
                "hourly_rate_cents": 540,  # divisible by 60 but below the 1000 minimum
                "pay_method": "HOURLY",
                "effective_from": "2026-01-01",
                "expected_worker_version": get_worker(worker["id"])["version"],
            },
            make_household_client_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_WAGE)

    def test_new_agreement_supersedes_prior_and_sets_effective_to(self, api):
        """PRD §3.4: "Creating an agreement automatically supersedes the worker's prior `ACTIVE` agreement, if one exists: the prior agreement's `effective_to` is set to the new agreement's `effective_from` minus one day, its `superseded_by_id` points at the new agreement, and its `status` becomes `SUPERSEDED`."
        PRD §3.4: "Agreements are listed per worker with an optional `status` filter; a separate read exposes the (zero-or-one-element) list of agreements a given agreement superseded."

        Design: Corner/entities/agreement_supersede_sets_effective_to_and_chain
        """
        employer, worker, _a = setup_classified_worker("AA")
        a1 = _a
        a2 = create_agreement(
            employer["id"], worker["id"], hourly_rate_cents=3600, effective_from="2026-03-01"
        )
        resp = api.get_agreement(a1["id"], make_payroll_admin_headers())
        old = validate_success(resp, 200)
        assert old["status"] == "SUPERSEDED"
        assert old["effective_to"] == "2026-02-28", (
            f"effective_to must be the new effective_from minus one day, got {old['effective_to']}"
        )
        assert old["superseded_by_id"] == a2["id"]

        resp = api.list_superseded_agreements(a2["id"], make_payroll_admin_headers())
        superseded, _meta = validate_paginated(resp)
        assert len(superseded) == 1
        assert superseded[0]["id"] == a1["id"]

    def test_agreement_create_with_stale_worker_version_returns_412(self, api):
        """PRD §2.7: "Creating an `EmploymentAgreement` for a worker requires the request to carry `expected_worker_version`, set to the `version` the client last observed on the parent `DomesticWorker`."
        PRD §2.7: "Because agreement creation supersedes the worker's current `ACTIVE` agreement, a mismatch against the worker's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) — the supersede target may itself have changed since the client last read the worker."

        Design: Corner/cross_cutting_layers/agreement_create_stale_occ
        """
        employer, worker, _a = setup_classified_worker("AA")
        stale_version = get_worker(worker["id"])["version"]
        a1 = create_agreement(employer["id"], worker["id"], stale_version)
        assert a1["status"] == "ACTIVE"

        resp = api.create_agreement(
            worker["id"],
            {
                "hourly_rate_cents": 3600,
                "pay_method": "HOURLY",
                "effective_from": "2026-03-01",
                "expected_worker_version": stale_version,
            },
            make_household_client_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        resp = api.get_agreement(a1["id"], make_payroll_admin_headers())
        assert validate_success(resp, 200)["status"] == "ACTIVE", (
            "the failed stale create must not fire the supersede side effect"
        )


class TestWorkerReadsAndTermination:
    def test_get_nonexistent_worker_returns_404(self, api):
        """PRD §2.10: "Nested URLs are validated strictly left-to-right: `/household-payroll/employers/{eid}/workers/{wid}` requires the employer identified by `{eid}` to exist first, then the worker identified by `{wid}` to exist and belong to that employer; the first segment that fails to resolve yields `ERR_NOT_FOUND` and no further segments are examined."

        Design: Corner/entities/worker_get_not_found_returns_404
        """
        resp = api.get_worker(NON_EXISTENT_UUID, make_payroll_admin_headers())
        body = resp.json()
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)

    def test_terminated_worker_is_terminal_lockdown(self, api):
        """PRD §3.4: "Terminating a worker not in `ACTIVE` is rejected with `ERR_INVALID_STATE`."
        PRD §3.4: "Classifying a worker not in `ONBOARDING` or `CLASSIFIED` is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/worker_terminate_is_terminal
        """
        employer, worker, _a = setup_active_worker("AA")
        terminated = terminate_worker(employer["id"], worker["id"])
        assert terminated["status"] == "TERMINATED"

        resp = api.terminate_worker(worker["id"], make_household_client_headers(employer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api.classify_worker(
            worker["id"],
            {"classification_answers": [
                {"question_key": "controls_schedule", "answer": "WORKER"},
                {"question_key": "supplies_own_tools", "answer": "WORKER"},
                {"question_key": "hires_own_substitutes", "answer": "ALLOWED"},
                {"question_key": "paid_by", "answer": "PROJECT_NOT_HOURS"},
            ]},
            make_household_client_headers(employer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTimesheetApproveRequiresActiveWorker:
    def test_approve_for_classified_worker_rejected(self, api):
        """PRD §3.5: "Approval requires the worker to be in `ACTIVE` status (otherwise `ERR_INVALID_STATE`) and requires that no `FINALIZED` `PayRun` covers the timesheet's period for this worker (also `ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/timesheet_approve_requires_worker_active
        """
        employer, worker, _a = setup_classified_worker("AA")
        ts_resp = api.create_timesheet(
            worker["id"],
            {
                "period_start": "2026-02-02",
                "period_end": "2026-02-09",
                "entries": [{"work_date": "2026-02-02", "worked_minutes": 480}],
            },
            make_worker_headers(worker["id"]),
        )
        ts = validate_success(ts_resp, 201)
        validate_success(
            api.submit_timesheet(ts["id"], make_worker_headers(worker["id"])), 200
        )

        resp = api.approve_timesheet(
            ts["id"], make_household_client_headers(employer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_failed_approve_leaves_timesheet_submitted(self, api):
        """PRD §3.5: "Approval requires the worker to be in `ACTIVE` status (otherwise `ERR_INVALID_STATE`) and requires that no `FINALIZED` `PayRun` covers the timesheet's period for this worker (also `ERR_INVALID_STATE`)."
        PRD §3.5: "A `HouseholdClient` may reject a `SUBMITTED` timesheet, returning it to `DRAFT` with no other side effects; or may approve it."

        Design: Difficulty/cross_entity_state_dependency/timesheet_approve_requires_worker_active
        """
        employer, worker, _a = setup_classified_worker("AA")
        ts_resp = api.create_timesheet(
            worker["id"],
            {
                "period_start": "2026-02-02",
                "period_end": "2026-02-09",
                "entries": [{"work_date": "2026-02-02", "worked_minutes": 480}],
            },
            make_worker_headers(worker["id"]),
        )
        ts = validate_success(ts_resp, 201)
        validate_success(
            api.submit_timesheet(ts["id"], make_worker_headers(worker["id"])), 200
        )

        resp = api.approve_timesheet(
            ts["id"], make_household_client_headers(employer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        resp = api.get_timesheet(ts["id"], make_payroll_admin_headers())
        assert validate_success(resp, 200)["status"] == "SUBMITTED", (
            "a rejected transition must leave the timesheet in SUBMITTED with no partial side effects"
        )
