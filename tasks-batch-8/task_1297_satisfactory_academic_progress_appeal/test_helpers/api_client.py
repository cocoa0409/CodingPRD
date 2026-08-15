"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sap"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---------------- programs ----------------
    def create_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}", headers=headers)

    # ---------------- terms ----------------
    def create_term(self, payload, headers):
        return self._request("POST", f"{PREFIX}/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"{PREFIX}/terms/{term_id}", headers=headers)

    def close_grading(self, term_id, headers):
        return self._request("POST", f"{PREFIX}/terms/{term_id}/close-grading", {}, headers)

    def evaluate_term(self, term_id, headers):
        return self._request("POST", f"{PREFIX}/terms/{term_id}/evaluate", {}, headers)

    # ---------------- students ----------------
    def create_student(self, payload, headers):
        return self._request("POST", f"{PREFIX}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/students", headers=headers, params=params)

    def get_sap_preview(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}/sap-preview", headers=headers)

    # ---------------- term enrollments ----------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/term-enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{PREFIX}/term-enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/term-enrollments", headers=headers, params=params)

    def post_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/term-enrollments/{enrollment_id}/post", payload, headers)

    def amend_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/term-enrollments/{enrollment_id}/amend", payload, headers)

    # ---------------- evaluations ----------------
    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"{PREFIX}/evaluations/{evaluation_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/evaluations", headers=headers, params=params)

    # ---------------- appeals ----------------
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"{PREFIX}/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/appeals", headers=headers, params=params)

    def screen_appeal(self, appeal_id, headers):
        return self._request("POST", f"{PREFIX}/appeals/{appeal_id}/screen", {}, headers)

    def request_info(self, appeal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals/{appeal_id}/request-info", payload, headers)

    def resubmit_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals/{appeal_id}/resubmit", payload, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals/{appeal_id}/decide", payload, headers)

    # ---------------- academic plans ----------------
    def create_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/plans", headers=headers, params=params)

    def revise_plan(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/plans/{plan_id}/revise", payload, headers)

    # ---------------- plan checkpoints ----------------
    def get_checkpoint(self, checkpoint_id, headers):
        return self._request("GET", f"{PREFIX}/checkpoints/{checkpoint_id}", headers=headers)

    def list_checkpoints(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/checkpoints", headers=headers, params=params)

    # ---------------- notifications ----------------
    def get_notification(self, notification_id, headers):
        return self._request("GET", f"{PREFIX}/notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/notifications", headers=headers, params=params)

    def dispatch_notifications(self, headers):
        return self._request("POST", f"{PREFIX}/notifications/dispatch", {}, headers)

    # ---------------- audit trail ----------------
    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/audit-events/{event_id}", headers=headers)

    def list_audit_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/audit-events", headers=headers, params=params)


api_client = ApiClient()
