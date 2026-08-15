"""API client: one method per endpoint defined in the PRD (all under /sleep-consulting)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Consultants ────────────────────────────────────
    def create_consultant(self, payload, headers):
        return self._request("POST", "/sleep-consulting/consultants", payload, headers)

    def get_consultant(self, consultant_id, headers):
        return self._request("GET", f"/sleep-consulting/consultants/{consultant_id}", headers=headers)

    # ─── Families ───────────────────────────────────────
    def register_family(self, payload, headers):
        return self._request("POST", "/sleep-consulting/families", payload, headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/sleep-consulting/families", headers=headers, params=params)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/sleep-consulting/families/{family_id}", headers=headers)

    # ─── Cases ──────────────────────────────────────────
    def create_case(self, payload, headers):
        return self._request("POST", "/sleep-consulting/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/sleep-consulting/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}", headers=headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/complete", headers=headers)

    # ─── Intake questionnaire ───────────────────────────
    def submit_questionnaire(self, case_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/questionnaire", payload, headers)

    def get_case_questionnaire(self, case_id, headers):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/questionnaire", headers=headers)

    def review_questionnaire(self, questionnaire_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/questionnaires/{questionnaire_id}/review", payload, headers)

    # ─── Sleep plans ────────────────────────────────────
    def create_plan(self, case_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/plans", payload, headers)

    def list_plans(self, case_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/plans", headers=headers, params=params)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/sleep-consulting/plans/{plan_id}/resume", headers=headers)

    # ─── Support packages ───────────────────────────────
    def purchase_package(self, case_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/packages", payload, headers)

    def list_packages(self, case_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/sleep-consulting/packages/{package_id}", headers=headers)

    def list_package_sessions(self, package_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/packages/{package_id}/troubleshooting-sessions", headers=headers, params=params)

    def list_package_messages(self, package_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/packages/{package_id}/messages", headers=headers, params=params)

    def list_package_refund_requests(self, package_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/packages/{package_id}/refund-requests", headers=headers, params=params)

    # ─── Nightly sleep logs ─────────────────────────────
    def submit_log(self, case_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/logs", payload, headers)

    def list_logs(self, case_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/logs", headers=headers, params=params)

    def review_log(self, log_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/logs/{log_id}/review", payload, headers)

    # ─── Troubleshooting sessions ───────────────────────
    def book_session(self, case_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/troubleshooting-sessions", payload, headers)

    def list_sessions(self, case_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/troubleshooting-sessions", headers=headers, params=params)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sleep-consulting/troubleshooting-sessions/{session_id}/complete", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sleep-consulting/troubleshooting-sessions/{session_id}/cancel", headers=headers)

    # ─── Messages ───────────────────────────────────────
    def send_message(self, case_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/messages", payload, headers)

    def list_messages(self, case_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/messages", headers=headers, params=params)

    def respond_message(self, message_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/messages/{message_id}/respond", payload, headers)

    # ─── Refund requests ────────────────────────────────
    def create_refund_request(self, case_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/cases/{case_id}/refund-requests", payload, headers)

    def list_refund_requests(self, case_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/refund-requests", headers=headers, params=params)

    def approve_refund(self, refund_id, headers):
        return self._request("POST", f"/sleep-consulting/refund-requests/{refund_id}/approve", headers=headers)

    def deny_refund(self, refund_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/refund-requests/{refund_id}/deny", payload, headers)

    def pay_refund(self, refund_id, headers):
        return self._request("POST", f"/sleep-consulting/refund-requests/{refund_id}/pay", headers=headers)

    # ─── Group courses and enrollments ──────────────────
    def create_course(self, payload, headers):
        return self._request("POST", "/sleep-consulting/group-courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/sleep-consulting/group-courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/sleep-consulting/group-courses/{course_id}", headers=headers)

    def enroll(self, course_id, payload, headers):
        return self._request("POST", f"/sleep-consulting/group-courses/{course_id}/enrollments", payload, headers)

    def list_course_enrollments(self, course_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/group-courses/{course_id}/enrollments", headers=headers, params=params)

    def list_case_enrollments(self, case_id, headers, params=None):
        return self._request("GET", f"/sleep-consulting/cases/{case_id}/enrollments", headers=headers, params=params)

    def cancel_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/sleep-consulting/enrollments/{enrollment_id}/cancel", headers=headers)

    # ─── Logical clock ──────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/sleep-consulting/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
