"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (mounted at server root, PRD §2.5 / §4) ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- students ---
    def create_student(self, payload: Dict, headers: Dict):
        return self._request("POST", "/sevis/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict):
        return self._request("GET", f"/sevis/students/{student_id}", headers=headers)

    # --- financial documents ---
    def submit_financial_document(self, student_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/students/{student_id}/financial-documents",
            payload, headers,
        )

    def list_financial_documents(self, student_id: str, headers: Dict,
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/sevis/students/{student_id}/financial-documents",
            headers=headers, params=params,
        )

    def review_financial_document(self, document_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/financial-documents/{document_id}/review",
            payload, headers,
        )

    # --- SEVIS records ---
    def create_sevis_record(self, student_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/students/{student_id}/sevis-records", payload, headers,
        )

    def list_sevis_records(self, student_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/students/{student_id}/sevis-records", headers=headers,
        )

    def initialize_sevis_record(self, record_id: str, headers: Dict):
        return self._request(
            "POST", f"/sevis/sevis-records/{record_id}/initialize", {}, headers,
        )

    def terminate_sevis_record(self, record_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/sevis-records/{record_id}/terminate", payload, headers,
        )

    # --- I-20 forms ---
    def create_i20_form(self, student_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/students/{student_id}/i20-forms", payload, headers,
        )

    def list_i20_forms(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/sevis/i20-forms", headers=headers, params=params)

    def get_i20_form(self, i20_id: str, headers: Dict):
        return self._request("GET", f"/sevis/i20-forms/{i20_id}", headers=headers)

    def issue_i20_form(self, i20_id: str, headers: Dict):
        return self._request("POST", f"/sevis/i20-forms/{i20_id}/issue", {}, headers)

    # --- term enrollments ---
    def create_term_enrollment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/sevis/term-enrollments", payload, headers)

    def list_term_enrollments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/sevis/term-enrollments", headers=headers, params=params,
        )

    def get_term_enrollment(self, enrollment_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/term-enrollments/{enrollment_id}", headers=headers,
        )

    def patch_term_enrollment(self, enrollment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "PATCH", f"/sevis/term-enrollments/{enrollment_id}", payload, headers,
        )

    def register_term_enrollment(self, enrollment_id: str, headers: Dict):
        return self._request(
            "POST", f"/sevis/term-enrollments/{enrollment_id}/register", {}, headers,
        )

    # --- reduced course loads ---
    def create_reduced_course_load(self, payload: Dict, headers: Dict):
        return self._request("POST", "/sevis/reduced-course-loads", payload, headers)

    def list_reduced_course_loads(self, enrollment_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/term-enrollments/{enrollment_id}/reduced-course-loads",
            headers=headers,
        )

    def decide_reduced_course_load(self, rcl_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/reduced-course-loads/{rcl_id}/decision", payload, headers,
        )

    # --- employment authorizations ---
    def create_employment_authorization(self, payload: Dict, headers: Dict):
        return self._request(
            "POST", "/sevis/employment-authorizations", payload, headers,
        )

    def list_employment_authorizations(self, headers: Dict,
                                       params: Optional[Dict] = None):
        return self._request(
            "GET", "/sevis/employment-authorizations", headers=headers, params=params,
        )

    def get_employment_authorization(self, auth_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/employment-authorizations/{auth_id}", headers=headers,
        )

    def transition_employment_authorization(self, auth_id: str, payload: Dict,
                                            headers: Dict):
        return self._request(
            "POST", f"/sevis/employment-authorizations/{auth_id}/transition",
            payload, headers,
        )

    # --- employment periods ---
    def create_employment_period(self, auth_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST",
            f"/sevis/employment-authorizations/{auth_id}/employment-periods",
            payload, headers,
        )

    def list_employment_periods(self, auth_id: str, headers: Dict):
        return self._request(
            "GET",
            f"/sevis/employment-authorizations/{auth_id}/employment-periods",
            headers=headers,
        )

    def delete_employment_period(self, period_id: str, headers: Dict):
        return self._request(
            "DELETE", f"/sevis/employment-periods/{period_id}", headers=headers,
        )

    # --- travel endorsements ---
    def create_travel_endorsement(self, i20_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/i20-forms/{i20_id}/travel-endorsements", payload, headers,
        )

    def list_travel_endorsements(self, i20_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/i20-forms/{i20_id}/travel-endorsements", headers=headers,
        )

    # --- transfer requests ---
    def create_transfer_request(self, student_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/students/{student_id}/transfer-requests",
            payload, headers,
        )

    def list_transfer_requests(self, student_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/students/{student_id}/transfer-requests", headers=headers,
        )

    def cancel_transfer_request(self, transfer_id: str, headers: Dict):
        return self._request(
            "POST", f"/sevis/transfer-requests/{transfer_id}/cancel", {}, headers,
        )

    # --- program extensions ---
    def create_program_extension(self, student_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/students/{student_id}/program-extensions",
            payload, headers,
        )

    def list_program_extensions(self, student_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/students/{student_id}/program-extensions", headers=headers,
        )

    def decide_program_extension(self, extension_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/program-extensions/{extension_id}/decision",
            payload, headers,
        )

    # --- status violations ---
    def create_status_violation(self, student_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/students/{student_id}/status-violations",
            payload, headers,
        )

    def list_status_violations(self, student_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/students/{student_id}/status-violations", headers=headers,
        )

    def transition_status_violation(self, violation_id: str, payload: Dict,
                                    headers: Dict):
        return self._request(
            "POST", f"/sevis/status-violations/{violation_id}/transition",
            payload, headers,
        )

    # --- address reports ---
    def create_address_report(self, student_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/sevis/students/{student_id}/address-reports", payload, headers,
        )

    def list_address_reports(self, student_id: str, headers: Dict):
        return self._request(
            "GET", f"/sevis/students/{student_id}/address-reports", headers=headers,
        )


api_client = ApiClient()
