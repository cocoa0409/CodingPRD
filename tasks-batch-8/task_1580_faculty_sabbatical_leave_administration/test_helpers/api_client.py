"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)

    def update_department(self, department_id, payload, headers):
        return self._request("PATCH", f"/departments/{department_id}", payload, headers)

    # --- faculty members ---
    def create_faculty_member(self, payload, headers):
        return self._request("POST", "/faculty-members", payload, headers)

    def list_faculty_members(self, headers, params=None):
        return self._request("GET", "/faculty-members", headers=headers, params=params)

    def get_faculty_member(self, faculty_id, headers):
        return self._request("GET", f"/faculty-members/{faculty_id}", headers=headers)

    def separate_faculty_member(self, faculty_id, payload, headers):
        return self._request("POST", f"/faculty-members/{faculty_id}/separate", payload, headers)

    def get_faculty_eligibility(self, faculty_id, headers, params=None):
        return self._request(
            "GET", f"/faculty-members/{faculty_id}/eligibility", headers=headers, params=params
        )

    def list_accrual_ledger_entries(self, faculty_id, headers, params=None):
        return self._request(
            "GET",
            f"/faculty-members/{faculty_id}/accrual-ledger-entries",
            headers=headers,
            params=params,
        )

    # --- accrual ---
    def run_accruals(self, payload, headers):
        return self._request("POST", "/accrual-runs", payload, headers)

    def create_accrual_ledger_entry(self, payload, headers):
        return self._request("POST", "/accrual-ledger-entries", payload, headers)

    # --- leave cycles ---
    def create_leave_cycle(self, payload, headers):
        return self._request("POST", "/leave-cycles", payload, headers)

    def list_leave_cycles(self, headers, params=None):
        return self._request("GET", "/leave-cycles", headers=headers, params=params)

    def get_leave_cycle(self, cycle_id, headers):
        return self._request("GET", f"/leave-cycles/{cycle_id}", headers=headers)

    def open_leave_cycle(self, cycle_id, headers):
        return self._request("POST", f"/leave-cycles/{cycle_id}/open", {}, headers)

    def close_leave_cycle(self, cycle_id, headers):
        return self._request("POST", f"/leave-cycles/{cycle_id}/close", {}, headers)

    def allocate_leave_cycle(self, cycle_id, headers):
        return self._request("POST", f"/leave-cycles/{cycle_id}/allocate", {}, headers)

    def finalize_leave_cycle(self, cycle_id, headers):
        return self._request("POST", f"/leave-cycles/{cycle_id}/finalize", {}, headers)

    # --- leave applications ---
    def create_leave_application(self, payload, headers):
        return self._request("POST", "/leave-applications", payload, headers)

    def list_leave_applications(self, headers, params=None):
        return self._request("GET", "/leave-applications", headers=headers, params=params)

    def get_leave_application(self, application_id, headers):
        return self._request("GET", f"/leave-applications/{application_id}", headers=headers)

    def submit_leave_application(self, application_id, headers):
        return self._request("POST", f"/leave-applications/{application_id}/submit", {}, headers)

    def request_application_revision(self, application_id, headers):
        return self._request(
            "POST", f"/leave-applications/{application_id}/request-revision", {}, headers
        )

    def withdraw_leave_application(self, application_id, headers):
        return self._request("POST", f"/leave-applications/{application_id}/withdraw", {}, headers)

    def decide_leave_application(self, application_id, payload, headers):
        return self._request("POST", f"/leave-applications/{application_id}/decide", payload, headers)

    # --- committee reviews ---
    def create_committee_review(self, payload, headers):
        return self._request("POST", "/committee-reviews", payload, headers)

    def list_committee_reviews(self, headers, params=None):
        return self._request("GET", "/committee-reviews", headers=headers, params=params)

    def get_committee_review(self, review_id, headers):
        return self._request("GET", f"/committee-reviews/{review_id}", headers=headers)

    def submit_committee_review(self, review_id, headers):
        return self._request("POST", f"/committee-reviews/{review_id}/submit", {}, headers)

    # --- coverage plans ---
    def create_coverage_plan(self, payload, headers):
        return self._request("POST", "/coverage-plans", payload, headers)

    def list_coverage_plans(self, headers, params=None):
        return self._request("GET", "/coverage-plans", headers=headers, params=params)

    def get_coverage_plan(self, plan_id, headers):
        return self._request("GET", f"/coverage-plans/{plan_id}", headers=headers)

    def submit_coverage_plan(self, plan_id, headers):
        return self._request("POST", f"/coverage-plans/{plan_id}/submit", {}, headers)

    def approve_coverage_plan(self, plan_id, headers):
        return self._request("POST", f"/coverage-plans/{plan_id}/approve", {}, headers)

    def request_plan_revision(self, plan_id, headers):
        return self._request("POST", f"/coverage-plans/{plan_id}/request-revision", {}, headers)

    # --- leave grants ---
    def list_leave_grants(self, headers, params=None):
        return self._request("GET", "/leave-grants", headers=headers, params=params)

    def get_leave_grant(self, grant_id, headers):
        return self._request("GET", f"/leave-grants/{grant_id}", headers=headers)

    def activate_leave_grant(self, grant_id, headers):
        return self._request("POST", f"/leave-grants/{grant_id}/activate", {}, headers)

    def complete_leave_grant(self, grant_id, headers):
        return self._request("POST", f"/leave-grants/{grant_id}/complete", {}, headers)

    def curtail_leave_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/leave-grants/{grant_id}/curtail", payload, headers)

    # --- external fellowships ---
    def create_external_fellowship(self, payload, headers):
        return self._request("POST", "/external-fellowships", payload, headers)

    def list_external_fellowships(self, headers, params=None):
        return self._request("GET", "/external-fellowships", headers=headers, params=params)

    def get_external_fellowship(self, fellowship_id, headers):
        return self._request("GET", f"/external-fellowships/{fellowship_id}", headers=headers)

    def verify_external_fellowship(self, fellowship_id, headers):
        return self._request("POST", f"/external-fellowships/{fellowship_id}/verify", {}, headers)

    def decline_external_fellowship(self, fellowship_id, headers):
        return self._request("POST", f"/external-fellowships/{fellowship_id}/decline", {}, headers)

    # --- service obligations ---
    def list_service_obligations(self, headers, params=None):
        return self._request("GET", "/service-obligations", headers=headers, params=params)

    def get_service_obligation(self, obligation_id, headers):
        return self._request("GET", f"/service-obligations/{obligation_id}", headers=headers)

    # --- repayment obligations ---
    def list_repayment_obligations(self, headers, params=None):
        return self._request("GET", "/repayment-obligations", headers=headers, params=params)

    def get_repayment_obligation(self, repayment_id, headers):
        return self._request("GET", f"/repayment-obligations/{repayment_id}", headers=headers)

    def list_repayment_payments(self, repayment_id, headers, params=None):
        return self._request(
            "GET",
            f"/repayment-obligations/{repayment_id}/payments",
            headers=headers,
            params=params,
        )

    def create_repayment_payment(self, repayment_id, payload, headers):
        return self._request(
            "POST", f"/repayment-obligations/{repayment_id}/payments", payload, headers
        )

    def waive_repayment_obligation(self, repayment_id, payload, headers):
        return self._request(
            "POST", f"/repayment-obligations/{repayment_id}/waive", payload, headers
        )

    # --- accomplishment reports ---
    def list_accomplishment_reports(self, headers, params=None):
        return self._request("GET", "/accomplishment-reports", headers=headers, params=params)

    def get_accomplishment_report(self, report_id, headers):
        return self._request("GET", f"/accomplishment-reports/{report_id}", headers=headers)

    def submit_accomplishment_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/accomplishment-reports/{report_id}/submit", payload, headers
        )

    def review_accomplishment_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/accomplishment-reports/{report_id}/review", payload, headers
        )


api_client = ApiClient()
