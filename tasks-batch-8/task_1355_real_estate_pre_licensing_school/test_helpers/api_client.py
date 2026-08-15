"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- system / test-driving ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_regulatory_sweep(self, headers):
        return self._request("POST", "/_admin/run-regulatory-sweep", headers=headers)

    # --- schools ---
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/schools", headers=headers, params=params)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def license_school(self, school_id, headers):
        return self._request("POST", f"/schools/{school_id}/license", headers=headers)

    def suspend_school(self, school_id, headers):
        return self._request("POST", f"/schools/{school_id}/suspend", headers=headers)

    def reinstate_school(self, school_id, headers):
        return self._request("POST", f"/schools/{school_id}/reinstate", headers=headers)

    def revoke_school(self, school_id, headers):
        return self._request("POST", f"/schools/{school_id}/revoke", headers=headers)

    def get_pass_rate_summary(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}/pass-rate-summary",
                             headers=headers)

    # --- courses ---
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def activate_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/activate", headers=headers)

    def retire_course(self, course_id, headers):
        return self._request("POST", f"/courses/{course_id}/retire", headers=headers)

    # --- course approvals ---
    def create_course_approval(self, course_id, payload, headers):
        return self._request("POST", f"/courses/{course_id}/approvals", payload, headers)

    def list_course_approvals(self, course_id, headers, params=None):
        return self._request("GET", f"/courses/{course_id}/approvals",
                             headers=headers, params=params)

    def get_approval(self, approval_id, headers):
        return self._request("GET", f"/approvals/{approval_id}", headers=headers)

    def decide_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/approvals/{approval_id}/decide", payload, headers)

    def resubmit_approval(self, approval_id, headers):
        return self._request("POST", f"/approvals/{approval_id}/resubmit", headers=headers)

    def renew_approval(self, approval_id, headers):
        return self._request("POST", f"/approvals/{approval_id}/renew", headers=headers)

    # --- instructors & their approvals ---
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/instructors", headers=headers, params=params)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def create_instructor_approval(self, instructor_id, payload, headers):
        return self._request("POST", f"/instructors/{instructor_id}/approvals",
                             payload, headers)

    def list_instructor_approvals(self, instructor_id, headers, params=None):
        return self._request("GET", f"/instructors/{instructor_id}/approvals",
                             headers=headers, params=params)

    def get_instructor_approval(self, approval_id, headers):
        return self._request("GET", f"/instructor-approvals/{approval_id}",
                             headers=headers)

    def decide_instructor_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/instructor-approvals/{approval_id}/decide",
                             payload, headers)

    def resubmit_instructor_approval(self, approval_id, headers):
        return self._request("POST", f"/instructor-approvals/{approval_id}/resubmit",
                             headers=headers)

    def renew_instructor_approval(self, approval_id, headers):
        return self._request("POST", f"/instructor-approvals/{approval_id}/renew",
                             headers=headers)

    # --- offerings ---
    def create_offering(self, payload, headers):
        return self._request("POST", "/offerings", payload, headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/offerings", headers=headers, params=params)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def update_offering(self, offering_id, payload, headers):
        return self._request("PUT", f"/offerings/{offering_id}", payload, headers)

    def publish_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/publish", headers=headers)

    def cancel_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/cancel", headers=headers)

    # --- students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    # --- enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw",
                             payload, headers)

    def pay_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/pay",
                             payload, headers)

    # --- attendance ---
    def create_attendance_record(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/attendance-records",
                             payload, headers)

    def list_attendance_records(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/attendance-records",
                             headers=headers, params=params)

    def void_attendance_record(self, record_id, headers):
        return self._request("POST", f"/attendance-records/{record_id}/void",
                             headers=headers)

    # --- exam attempts ---
    def create_exam_attempt(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/exam-attempts",
                             payload, headers)

    def list_enrollment_exam_attempts(self, enrollment_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enrollment_id}/exam-attempts",
                             headers=headers, params=params)

    def list_exam_attempts(self, headers, params=None):
        return self._request("GET", "/exam-attempts", headers=headers, params=params)

    def get_exam_attempt(self, attempt_id, headers):
        return self._request("GET", f"/exam-attempts/{attempt_id}", headers=headers)

    def verify_exam_attempt(self, attempt_id, headers):
        return self._request("POST", f"/exam-attempts/{attempt_id}/verify",
                             headers=headers)

    def score_exam_attempt(self, attempt_id, payload, headers):
        return self._request("POST", f"/exam-attempts/{attempt_id}/score",
                             payload, headers)

    def invalidate_exam_attempt(self, attempt_id, payload, headers):
        return self._request("POST", f"/exam-attempts/{attempt_id}/invalidate",
                             payload, headers)

    # --- certificates ---
    def issue_certificate(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/certificate",
                             headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def revoke_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/certificates/{certificate_id}/revoke",
                             payload, headers)

    # --- refunds ---
    def list_refund_requests(self, headers, params=None):
        return self._request("GET", "/refund-requests", headers=headers, params=params)

    def get_refund_request(self, refund_request_id, headers):
        return self._request("GET", f"/refund-requests/{refund_request_id}",
                             headers=headers)

    def approve_refund_request(self, refund_request_id, headers):
        return self._request("POST", f"/refund-requests/{refund_request_id}/approve",
                             headers=headers)

    def deny_refund_request(self, refund_request_id, payload, headers):
        return self._request("POST", f"/refund-requests/{refund_request_id}/deny",
                             payload, headers)

    def pay_refund_request(self, refund_request_id, headers):
        return self._request("POST", f"/refund-requests/{refund_request_id}/pay",
                             headers=headers)

    # --- credit reports ---
    def create_credit_report(self, payload, headers):
        return self._request("POST", "/credit-reports", payload, headers)

    def list_credit_reports(self, headers, params=None):
        return self._request("GET", "/credit-reports", headers=headers, params=params)

    def get_credit_report(self, report_id, headers):
        return self._request("GET", f"/credit-reports/{report_id}", headers=headers)

    def submit_credit_report(self, report_id, headers):
        return self._request("POST", f"/credit-reports/{report_id}/submit",
                             headers=headers)

    def acknowledge_credit_report(self, report_id, headers):
        return self._request("POST", f"/credit-reports/{report_id}/acknowledge",
                             headers=headers)

    def reject_credit_report(self, report_id, payload, headers):
        return self._request("POST", f"/credit-reports/{report_id}/reject",
                             payload, headers)

    def revise_credit_report(self, report_id, headers):
        return self._request("POST", f"/credit-reports/{report_id}/revise",
                             headers=headers)

    def create_credit_report_amendment(self, report_id, payload, headers):
        return self._request("POST", f"/credit-reports/{report_id}/amendments",
                             payload, headers)

    # --- equivalency grants ---
    def create_equivalency_grant(self, payload, headers):
        return self._request("POST", "/equivalency-grants", payload, headers)

    def list_equivalency_grants(self, headers, params=None):
        return self._request("GET", "/equivalency-grants", headers=headers, params=params)

    def get_equivalency_grant(self, grant_id, headers):
        return self._request("GET", f"/equivalency-grants/{grant_id}", headers=headers)

    def revoke_equivalency_grant(self, grant_id, headers):
        return self._request("POST", f"/equivalency-grants/{grant_id}/revoke",
                             headers=headers)

    # --- audit ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)


api_client = ApiClient()
