"""Role-based access control and segregation-of-duties denials."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_employer,
    create_filing,
    create_rule_pack,
    create_state_rule_pack_payload,
    create_timesheet,
    create_worker,
    get_filing,
    get_timesheet,
    make_compliance_officer_headers,
    make_household_client_headers,
    make_payroll_admin_headers,
    make_worker_headers,
    prepare_filing,
    setup_active_worker,
    submit_timesheet,
    validate_error,
    validate_success,
)


class TestAuthentication:
    def test_request_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "Requests missing either header, or carrying a role not in this list, are rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/request_missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_employer(
            {
                "legal_name": "Anon",
                "primary_state_code": "AA",
                "fein": "123456789",
                "pay_frequency": "WEEKLY",
            },
            {"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleGates:
    def test_household_client_cannot_create_rule_pack(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorization list; a role that is not permitted on the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/household_client_cannot_create_rule_pack
        """
        resp = api.create_state_rule_pack(
            create_state_rule_pack_payload("RB", sit_rate=0.0),
            make_household_client_headers("11111111-1111-1111-1111-111111111111"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_payroll_admin_cannot_suspend_employer(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorization list; a role that is not permitted on the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/household-payroll/employers/{id}/suspend` | Suspend an employer | ComplianceOfficer |"

        Design: Corner/rbac/payroll_admin_cannot_suspend_employer
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        resp = api.suspend_employer(employer["id"], make_payroll_admin_headers("admin-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_worker_cannot_approve_own_timesheet(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorization list; a role that is not permitted on the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/household-payroll/timesheets/{id}/approve` | Approve a SUBMITTED timesheet | HouseholdClient |"

        Design: Corner/rbac/worker_cannot_approve_own_timesheet
        """
        employer, worker, _a = setup_active_worker("AA")
        ts = create_timesheet(
            worker["id"], "2026-02-02", "2026-02-09",
            [{"work_date": "2026-02-02", "worked_minutes": 480}],
        )
        submit_timesheet(worker["id"], ts["id"])
        resp = api.approve_timesheet(ts["id"], make_worker_headers(worker["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

        assert get_timesheet(ts["id"])["status"] == "SUBMITTED"

    def test_payroll_admin_cannot_submit_filing(self, api):
        """PRD §2.1: "Once authenticated, the role is checked against the endpoint's authorization list; a role that is not permitted on the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/household-payroll/quarterly-filings/{id}/submit` | Submit a PREPARED filing | ComplianceOfficer |"

        Design: Corner/rbac/payroll_admin_cannot_submit_filing
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        filing = create_filing(employer["id"], 2026, 1)
        prepare_filing(filing["id"], "admin-1")
        # A different admin (not the preparer) is still role-denied on submit.
        resp = api.submit_quarterly_filing(
            filing["id"], make_payroll_admin_headers("admin-9")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


class TestSegregationOfDuties:
    def test_filing_submitter_same_as_preparer_rejected(self, api):
        """PRD §2.1: "The segregation-of-duties rule deserves explicit statement: the `X-User-ID` that prepares a quarterly filing may not be the `X-User-ID` that submits it. An attempt to submit with the same id is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/filing_submitter_same_as_preparer_rejected
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        filing = create_filing(employer["id"], 2026, 1)
        prepare_filing(filing["id"], "admin-1")
        # Correct role (ComplianceOfficer) but the same user id as the preparer.
        resp = api.submit_quarterly_filing(
            filing["id"], make_compliance_officer_headers("admin-1")
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        assert get_filing(filing["id"], employer["id"])["status"] == "PREPARED"


class TestEntityBackedOwnership:
    def test_household_client_cannot_touch_other_employer(self, api):
        """PRD §2.1: "When `X-User-Role` is `HouseholdClient`, `X-User-ID` is the `id` of the acting `HouseholdEmployer`; ownership checks on any resource that references a `HouseholdEmployer` compare the resource's foreign-key field (typically `employer_id` reached through the URL path or a parent worker) to `X-User-ID`."
        PRD §2.1: "A mismatch on either entity-backed role yields `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/household_client_cannot_touch_other_employer
        """
        create_rule_pack("AA")
        e1 = create_employer("AA", legal_name="Fam One")
        e2 = create_employer("AA", legal_name="Fam Two", fein="223456789")
        resp = api.create_worker(
            e2["id"],
            {
                "full_name": "Intruder",
                "work_state_code": "AA",
                "hire_date": "2026-01-05",
                "work_arrangement": "LIVE_OUT",
            },
            make_household_client_headers(e1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)

    def test_worker_reading_other_worker_returns_403(self, api):
        """PRD §2.1: "When `X-User-Role` is `Worker`, `X-User-ID` is the `id` of the acting `DomesticWorker`; ownership checks on any resource that references a `DomesticWorker` (timesheets, leave requests, the worker's own paychecks) compare the resource's `worker_id` or the path's worker identifier to `X-User-ID`."
        PRD §2.1: "A mismatch on either entity-backed role yields `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/worker_reading_other_worker_returns_forbidden
        """
        create_rule_pack("AA")
        employer = create_employer("AA")
        w1 = create_worker(employer["id"], full_name="Peer One")
        w2 = create_worker(employer["id"], full_name="Peer Two")
        resp = api.get_worker(w2["id"], make_worker_headers(w1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
