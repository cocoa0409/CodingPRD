"""Thin typed client: exactly one method per endpoint of the PRD endpoint table."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per documented endpoint. No validation happens here."""

    # --- Logical clock ---------------------------------------------------

    def set_clock(self, current_utc: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # --- Partnerships ----------------------------------------------------

    def create_partnership(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/partnerships", payload, headers)

    def get_partnership(self, partnership_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/partnerships/{partnership_id}", None, headers)

    def list_partnerships(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", "/partnerships", params, headers)

    def amend_partnership_terms(
        self, partnership_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/partnerships/{partnership_id}/terms", payload, headers)

    def post_contract_action(
        self, partnership_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/partnerships/{partnership_id}/contract-actions", payload, headers)

    def get_revenue_summary(self, partnership_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/partnerships/{partnership_id}/revenue-summary", None, headers)

    # --- Programs --------------------------------------------------------

    def create_program(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}", None, headers)

    def list_programs(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", "/programs", params, headers)

    def post_program_lifecycle_action(
        self, program_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/lifecycle-actions", payload, headers)

    # --- Courses ---------------------------------------------------------

    def create_course(
        self, program_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/courses", payload, headers)

    def get_course(self, course_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/courses/{course_id}", None, headers)

    def list_courses(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", "/courses", params, headers)

    def amend_course(
        self, course_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("PATCH", f"/courses/{course_id}", payload, headers)

    def post_course_design_action(
        self, course_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/courses/{course_id}/design-actions", payload, headers)

    # --- Service scope ---------------------------------------------------

    def create_service_scope_assignment(
        self, program_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/service-scope-assignments", payload, headers)

    def list_service_scope_assignments(
        self,
        program_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/service-scope-assignments", params, headers)

    # --- Enrollment counselors -------------------------------------------

    def create_enrollment_counselor(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", "/enrollment-counselors", payload, headers)

    def get_enrollment_counselor(self, counselor_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/enrollment-counselors/{counselor_id}", None, headers)

    def list_enrollment_counselors(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", "/enrollment-counselors", params, headers)

    def file_compensation_plan(
        self, counselor_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/enrollment-counselors/{counselor_id}/compensation-plan", payload, headers)

    def post_compliance_review(
        self, counselor_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/enrollment-counselors/{counselor_id}/compliance-review", payload, headers)

    def create_counselor_performance_run(
        self, partnership_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/partnerships/{partnership_id}/counselor-performance-runs", payload, headers)

    # --- Leads -----------------------------------------------------------

    def create_lead(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("POST", "/leads", payload, headers)

    def get_lead(self, lead_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/leads/{lead_id}", None, headers)

    def list_leads(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", "/leads", params, headers)

    def advance_lead(
        self, lead_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/leads/{lead_id}/advance", payload, headers)

    def enroll_lead(
        self, lead_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/leads/{lead_id}/enroll", payload, headers)

    # --- Enrollments -----------------------------------------------------

    def get_enrollment(self, enrollment_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/enrollments/{enrollment_id}", None, headers)

    def list_enrollments(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", "/enrollments", params, headers)

    def post_academic_action(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/enrollments/{enrollment_id}/academic-actions", payload, headers)

    def create_tuition_payment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/enrollments/{enrollment_id}/tuition-payments", payload, headers)

    def list_tuition_payments(
        self,
        enrollment_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", f"/enrollments/{enrollment_id}/tuition-payments", params, headers)

    # --- Marketing ledger ------------------------------------------------

    def create_marketing_spend_entry(
        self, program_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/marketing-spend-entries", payload, headers)

    def list_marketing_spend_entries(
        self,
        program_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/marketing-spend-entries", params, headers)

    # --- Remittance statements -------------------------------------------

    def create_remittance_statement(
        self, partnership_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/partnerships/{partnership_id}/remittance-statements", payload, headers)

    def get_remittance_statement(self, statement_id: str, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        return self._request("GET", f"/remittance-statements/{statement_id}", None, headers)

    def list_remittance_statements(
        self, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", "/remittance-statements", params, headers)

    def post_statement_action(
        self, statement_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/remittance-statements/{statement_id}/actions", payload, headers)

    # --- Teach-out plans -------------------------------------------------

    def create_teach_out_plan(
        self, program_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/programs/{program_id}/teach-out-plans", payload, headers)

    def list_teach_out_plans(
        self,
        program_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/teach-out-plans", params, headers)

    def certify_teach_out_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"/teach-out-plans/{plan_id}/certify", payload, headers)


api_client = ApiClient()
