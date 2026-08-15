"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Dual Enrollment & Concurrent Credit API."""

    # --- Logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/_clock/set_current_utc", payload, headers)

    # --- High schools ---
    def create_high_school(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/high-schools", payload, headers)

    def list_high_schools(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/high-schools", headers=headers, params=params)

    def get_high_school(self, school_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/high-schools/{school_id}", headers=headers)

    def suspend_high_school(self, school_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/high-schools/{school_id}/suspend", {}, headers)

    # --- Academic terms ---
    def create_term(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/terms", payload, headers)

    def list_terms(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/terms", headers=headers, params=params)

    def get_term(self, term_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/terms/{term_id}", headers=headers)

    def open_term_registration(self, term_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/terms/{term_id}/open-registration", {}, headers)

    def close_term_registration(self, term_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/terms/{term_id}/close-registration", {}, headers)

    # --- Students ---
    def create_student(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/students", payload, headers)

    def list_students(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/students", headers=headers, params=params)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/students/{student_id}", headers=headers)

    def suspend_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/students/{student_id}/suspend", {}, headers)

    # --- Courses ---
    def create_course(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/courses", payload, headers)

    def list_courses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/courses", headers=headers, params=params)

    def get_course(self, course_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/courses/{course_id}", headers=headers)

    def retire_course(self, course_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/courses/{course_id}/retire", {}, headers)

    # --- Prerequisites ---
    def create_prerequisite(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/prerequisites", payload, headers)

    def list_prerequisites(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/prerequisites", headers=headers, params=params)

    def get_prerequisite(self, prereq_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/prerequisites/{prereq_id}", headers=headers)

    # --- Placement records ---
    def create_placement_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/placement-records", payload, headers)

    def list_placement_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/placement-records", headers=headers, params=params)

    def get_placement_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/placement-records/{record_id}", headers=headers)

    # --- Instructors ---
    def create_instructor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/instructors", payload, headers)

    def list_instructors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/instructors", headers=headers, params=params)

    def get_instructor(self, instructor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/instructors/{instructor_id}", headers=headers)

    # --- Credential applications ---
    def create_credential_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/credential-applications", payload, headers)

    def list_credential_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/credential-applications", headers=headers, params=params)

    def get_credential_application(self, app_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/credential-applications/{app_id}", headers=headers)

    def begin_credential_review(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/credential-applications/{app_id}/begin-review", {}, headers
        )

    def approve_credential_application(
        self, app_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dual-credit/credential-applications/{app_id}/approve", payload or {}, headers
        )

    def deny_credential_application(
        self, app_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dual-credit/credential-applications/{app_id}/deny", payload or {}, headers
        )

    def request_credential_revision(
        self, app_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/dual-credit/credential-applications/{app_id}/request-revision",
            payload or {},
            headers,
        )

    def resubmit_credential_application(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/credential-applications/{app_id}/resubmit", {}, headers
        )

    # --- Course offerings ---
    def create_offering(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/offerings", payload, headers)

    def list_offerings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/offerings", headers=headers, params=params)

    def get_offering(self, offering_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/offerings/{offering_id}", headers=headers)

    def open_offering(self, offering_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/offerings/{offering_id}/open", {}, headers)

    def start_offering_session(self, offering_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/offerings/{offering_id}/start-session", {}, headers
        )

    def begin_offering_grading(self, offering_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/offerings/{offering_id}/begin-grading", {}, headers
        )

    def finalize_offering(self, offering_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/offerings/{offering_id}/finalize", {}, headers)

    def cancel_offering(self, offering_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/offerings/{offering_id}/cancel", {}, headers)

    # --- Enrollments ---
    def create_enrollment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/enrollments", payload, headers)

    def list_enrollments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/enrollments/{enrollment_id}", headers=headers)

    def confirm_enrollment(self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/enrollments/{enrollment_id}/confirm", payload, headers
        )

    def drop_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/enrollments/{enrollment_id}/drop", {}, headers)

    def withdraw_enrollment(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/enrollments/{enrollment_id}/withdraw", {}, headers
        )

    def reinstate_enrollment(
        self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dual-credit/enrollments/{enrollment_id}/reinstate", payload, headers
        )

    def cancel_waitlist(self, enrollment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/enrollments/{enrollment_id}/cancel-waitlist", {}, headers
        )

    def submit_grade(self, enrollment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/enrollments/{enrollment_id}/submit-grade", payload, headers
        )

    def get_transfer_evaluation(
        self, enrollment_id: str, target_institution: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"/dual-credit/enrollments/{enrollment_id}/transfer-evaluation",
            headers=headers,
            params={"target_institution": target_institution},
        )

    # --- Transcript entries ---
    def list_transcript_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/transcript-entries", headers=headers, params=params)

    def get_transcript_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/transcript-entries/{entry_id}", headers=headers)

    def post_transcript_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/transcript-entries/{entry_id}/post", {}, headers
        )

    def void_transcript_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/transcript-entries/{entry_id}/void", {}, headers
        )

    # --- Funding agreements ---
    def create_funding_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/funding-agreements", payload, headers)

    def list_funding_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/funding-agreements", headers=headers, params=params)

    def get_funding_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/dual-credit/funding-agreements/{agreement_id}", headers=headers
        )

    # --- Invoices, payments, refunds ---
    def list_invoices(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/invoices/{invoice_id}", headers=headers)

    def create_payment(self, invoice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/dual-credit/invoices/{invoice_id}/payments", payload, headers
        )

    def list_payments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dual-credit/payments", headers=headers, params=params)

    def get_payment(self, payment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dual-credit/payments/{payment_id}", headers=headers)

    def refund_invoice(self, invoice_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/dual-credit/invoices/{invoice_id}/refund", {}, headers)

    # --- Articulation agreements ---
    def create_articulation_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dual-credit/articulation-agreements", payload, headers)

    def list_articulation_agreements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", "/dual-credit/articulation-agreements", headers=headers, params=params
        )

    def get_articulation_agreement(self, agreement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/dual-credit/articulation-agreements/{agreement_id}", headers=headers
        )


api_client = ApiClient()
