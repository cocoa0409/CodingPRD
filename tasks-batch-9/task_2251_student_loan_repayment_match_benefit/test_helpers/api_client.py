"""
Typed HTTP client with one method per endpoint declared by the PRD.

Every method returns the raw `requests.Response` so tests can assert status
codes themselves. Creation endpoints answer `201 Created`; every other
operation — state transitions, computed runs, reads and the logical-clock
capability — answers `200 OK`.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per PRD endpoint."""

    # ------------------------------------------------------------------
    # Plan years
    # ------------------------------------------------------------------

    def create_plan_year(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/plan-years", payload, headers)

    def get_plan_year(self, plan_year_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/plan-years/{plan_year_id}", headers=headers)

    def list_plan_years(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", "/plan-years", headers=headers, params=params)

    def set_plan_year_status(
        self, plan_year_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/plan-years/{plan_year_id}/status", payload, headers)

    def run_true_up(
        self, plan_year_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/plan-years/{plan_year_id}/true-up", payload or {}, headers)

    # ------------------------------------------------------------------
    # Plan amendments
    # ------------------------------------------------------------------

    def create_plan_amendment(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/plan-amendments", payload, headers)

    def get_plan_amendment(self, amendment_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/plan-amendments/{amendment_id}", headers=headers)

    def list_plan_amendments(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/plan-amendments", headers=headers, params=params)

    def set_amendment_status(
        self, amendment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/plan-amendments/{amendment_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------

    def create_employee(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", "/employees", headers=headers, params=params)

    def create_employment_event(
        self, employee_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/employees/{employee_id}/employment-events", payload, headers
        )

    def get_audit_packet(self, employee_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/employees/{employee_id}/audit-packet", headers=headers)

    # ------------------------------------------------------------------
    # Leave events
    # ------------------------------------------------------------------

    def create_leave_event(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/leave-events", payload, headers)

    def get_leave_event(self, leave_event_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/leave-events/{leave_event_id}", headers=headers)

    def list_leave_events(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/leave-events", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Payroll periods
    # ------------------------------------------------------------------

    def create_payroll_period(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/payroll-periods", payload, headers)

    def get_payroll_period(
        self, payroll_period_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/payroll-periods/{payroll_period_id}", headers=headers)

    def list_payroll_periods(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/payroll-periods", headers=headers, params=params)

    def set_payroll_period_status(
        self, payroll_period_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/payroll-periods/{payroll_period_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Contribution records (payroll lines)
    # ------------------------------------------------------------------

    def create_contribution_record(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/contribution-records", payload, headers)

    def get_contribution_record(
        self, contribution_record_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/contribution-records/{contribution_record_id}", headers=headers
        )

    def list_contribution_records(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/contribution-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Loan accounts
    # ------------------------------------------------------------------

    def create_loan_account(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/loan-accounts", payload, headers)

    def get_loan_account(self, loan_account_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/loan-accounts/{loan_account_id}", headers=headers)

    def list_loan_accounts(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/loan-accounts", headers=headers, params=params)

    def set_loan_account_verification(
        self, loan_account_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loan-accounts/{loan_account_id}/verification", payload, headers
        )

    # ------------------------------------------------------------------
    # Loan certifications (annual claims)
    # ------------------------------------------------------------------

    def create_loan_certification(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/loan-certifications", payload, headers)

    def get_loan_certification(
        self, certification_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/loan-certifications/{certification_id}", headers=headers)

    def list_loan_certifications(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/loan-certifications", headers=headers, params=params)

    def add_certification_line(
        self, certification_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loan-certifications/{certification_id}/lines", payload, headers
        )

    def list_certification_lines_of(
        self, certification_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/loan-certifications/{certification_id}/lines",
            headers=headers,
            params=params,
        )

    def get_certification_line(
        self, certification_line_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/certification-lines/{certification_line_id}", headers=headers
        )

    def list_certification_lines(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/certification-lines", headers=headers, params=params)

    def submit_certification(
        self, certification_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loan-certifications/{certification_id}/submit", payload or {}, headers
        )

    def decide_certification(
        self, certification_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loan-certifications/{certification_id}/decision", payload, headers
        )

    def audit_hold_certification(
        self, certification_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loan-certifications/{certification_id}/audit-hold", payload, headers
        )

    def audit_release_certification(
        self, certification_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loan-certifications/{certification_id}/audit-release", payload, headers
        )

    # ------------------------------------------------------------------
    # Match allocations and correction adjustments
    # ------------------------------------------------------------------

    def get_match_allocation(self, allocation_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/match-allocations/{allocation_id}", headers=headers)

    def list_match_allocations(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/match-allocations", headers=headers, params=params)

    def create_allocation_correction(
        self, allocation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/match-allocations/{allocation_id}/corrections", payload, headers
        )

    def get_correction_adjustment(
        self, correction_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/correction-adjustments/{correction_id}", headers=headers)

    def list_correction_adjustments(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/correction-adjustments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Funding batches
    # ------------------------------------------------------------------

    def create_funding_batch(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/funding-batches", payload, headers)

    def get_funding_batch(
        self, funding_batch_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/funding-batches/{funding_batch_id}", headers=headers)

    def list_funding_batches(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/funding-batches", headers=headers, params=params)

    def transmit_funding_batch(
        self, funding_batch_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/funding-batches/{funding_batch_id}/transmit", payload or {}, headers
        )

    def settle_funding_batch(
        self, funding_batch_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/funding-batches/{funding_batch_id}/settlement", payload, headers
        )

    # ------------------------------------------------------------------
    # Forfeiture records
    # ------------------------------------------------------------------

    def get_forfeiture_record(self, forfeiture_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/forfeiture-records/{forfeiture_id}", headers=headers)

    def list_forfeiture_records(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/forfeiture-records", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Nondiscrimination tests
    # ------------------------------------------------------------------

    def create_nondiscrimination_test(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/nondiscrimination-tests", payload, headers)

    def get_nondiscrimination_test(
        self, test_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/nondiscrimination-tests/{test_id}", headers=headers)

    def list_nondiscrimination_tests(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/nondiscrimination-tests", headers=headers, params=params)

    def compute_nondiscrimination_test(
        self, test_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/nondiscrimination-tests/{test_id}/compute", payload or {}, headers
        )

    def correct_nondiscrimination_test(
        self, test_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/nondiscrimination-tests/{test_id}/correction", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock capability
    # ------------------------------------------------------------------

    def set_clock(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
