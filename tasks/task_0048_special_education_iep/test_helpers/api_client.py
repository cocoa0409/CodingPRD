"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving, PRD §3.10) ────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Student (PRD §3.1) ─────────────────────────────────────
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    # ─── Evaluation (PRD §3.2) ──────────────────────────────────
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/evaluations", payload, headers)

    def get_evaluation(self, eval_id, headers):
        return self._request("GET", f"/evaluations/{eval_id}", headers=headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/evaluations", headers=headers, params=params)

    def request_consent(self, eval_id, headers):
        return self._request(
            "POST", f"/evaluations/{eval_id}/request-consent", headers=headers
        )

    def begin_evaluation(self, eval_id, headers):
        return self._request("POST", f"/evaluations/{eval_id}/begin", headers=headers)

    def finalize_evaluation(self, eval_id, headers):
        return self._request("POST", f"/evaluations/{eval_id}/finalize", headers=headers)

    # ─── ConsentRequest (PRD §3.4) ──────────────────────────────
    def get_consent_request(self, cr_id, headers):
        return self._request("GET", f"/consent-requests/{cr_id}", headers=headers)

    def list_consent_requests(self, headers, params=None):
        return self._request(
            "GET", "/consent-requests", headers=headers, params=params
        )

    def decide_consent(self, cr_id, payload, headers):
        return self._request(
            "POST", f"/consent-requests/{cr_id}/decide", payload, headers
        )

    def revoke_consent(self, cr_id, headers):
        return self._request("POST", f"/consent-requests/{cr_id}/revoke", headers=headers)

    # ─── IEP (PRD §3.5) ─────────────────────────────────────────
    def create_iep(self, payload, headers):
        return self._request("POST", "/ieps", payload, headers)

    def get_iep(self, iep_id, headers):
        return self._request("GET", f"/ieps/{iep_id}", headers=headers)

    def list_ieps(self, headers, params=None):
        return self._request("GET", "/ieps", headers=headers, params=params)

    def hold_meeting(self, iep_id, headers):
        return self._request("POST", f"/ieps/{iep_id}/hold-meeting", headers=headers)

    def activate_iep(self, iep_id, headers):
        return self._request("POST", f"/ieps/{iep_id}/activate", headers=headers)

    def open_amendment(self, iep_id, payload, headers):
        return self._request(
            "POST", f"/ieps/{iep_id}/open-amendment", payload, headers
        )

    def archive_iep(self, iep_id, headers):
        return self._request("POST", f"/ieps/{iep_id}/archive", headers=headers)

    # ─── Goal (PRD §3.6) ────────────────────────────────────────
    def create_goal(self, payload, headers):
        return self._request("POST", "/goals", payload, headers)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/goals/{goal_id}", headers=headers)

    def list_goals(self, headers, params=None):
        return self._request("GET", "/goals", headers=headers, params=params)

    def discontinue_goal(self, goal_id, headers):
        return self._request("POST", f"/goals/{goal_id}/discontinue", headers=headers)

    # ─── ProgressReport (PRD §3.6) ──────────────────────────────
    def create_progress_report(self, payload, headers):
        return self._request("POST", "/progress-reports", payload, headers)

    def get_progress_report(self, pr_id, headers):
        return self._request("GET", f"/progress-reports/{pr_id}", headers=headers)

    def list_progress_reports(self, headers, params=None):
        return self._request(
            "GET", "/progress-reports", headers=headers, params=params
        )

    # ─── RelatedService (PRD §3.8) ──────────────────────────────
    def create_related_service(self, payload, headers):
        return self._request("POST", "/related-services", payload, headers)

    def get_related_service(self, rs_id, headers):
        return self._request("GET", f"/related-services/{rs_id}", headers=headers)

    def list_related_services(self, headers, params=None):
        return self._request(
            "GET", "/related-services", headers=headers, params=params
        )

    def discontinue_related_service(self, rs_id, payload, headers):
        return self._request(
            "DELETE", f"/related-services/{rs_id}", payload, headers
        )

    # ─── TransitionPlan (PRD §3.9) ──────────────────────────────
    def create_transition_plan(self, payload, headers):
        return self._request("POST", "/transition-plans", payload, headers)

    def get_transition_plan(self, tp_id, headers):
        return self._request("GET", f"/transition-plans/{tp_id}", headers=headers)

    def list_transition_plans(self, headers, params=None):
        return self._request(
            "GET", "/transition-plans", headers=headers, params=params
        )

    def adopt_transition_plan(self, tp_id, headers):
        return self._request(
            "POST", f"/transition-plans/{tp_id}/adopt", headers=headers
        )


api_client = ApiClient()
