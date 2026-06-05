"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ReviewCycle ----
    def create_cycle(self, payload, headers):
        return self._request("POST", "/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def create_rating_band(self, cycle_id, payload, headers):
        return self._request("POST", f"/cycles/{cycle_id}/rating-bands", payload, headers)

    def list_rating_bands(self, cycle_id, headers, params=None):
        return self._request("GET", f"/cycles/{cycle_id}/rating-bands", headers=headers, params=params)

    def open_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/open", {}, headers)

    def start_calibration(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/start-calibration", {}, headers)

    def start_comp_planning(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/start-comp-planning", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/close", {}, headers)

    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    # ---- Review ----
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def patch_review(self, review_id, payload, headers):
        return self._request("PATCH", f"/reviews/{review_id}", payload, headers)

    def begin_self_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/begin-self-review", {}, headers)

    def submit_self(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/submit-self", {}, headers)

    def submit_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/submit", {}, headers)

    def return_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/return", {}, headers)

    def reopen_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/reopen", {}, headers)

    # ---- Goal ----
    def create_goal(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/goals", payload, headers)

    def list_goals(self, review_id, headers, params=None):
        return self._request("GET", f"/reviews/{review_id}/goals", headers=headers, params=params)

    def score_goal(self, goal_id, payload, headers):
        return self._request("POST", f"/goals/{goal_id}/score", payload, headers)

    # ---- FeedbackRequest ----
    def create_feedback_request(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/feedback-requests", payload, headers)

    def list_review_feedback_requests(self, review_id, headers, params=None):
        return self._request("GET", f"/reviews/{review_id}/feedback-requests", headers=headers, params=params)

    def submit_feedback(self, feedback_id, payload, headers):
        return self._request("POST", f"/feedback-requests/{feedback_id}/submit", payload, headers)

    def decline_feedback(self, feedback_id, headers):
        return self._request("POST", f"/feedback-requests/{feedback_id}/decline", {}, headers)

    def list_feedback_requests(self, headers, params=None):
        return self._request("GET", "/feedback-requests", headers=headers, params=params)

    def get_feedback_request(self, feedback_id, headers):
        return self._request("GET", f"/feedback-requests/{feedback_id}", headers=headers)

    # ---- CalibrationSession ----
    def create_calibration_session(self, payload, headers):
        return self._request("POST", "/calibration-sessions", payload, headers)

    def list_calibration_sessions(self, headers, params=None):
        return self._request("GET", "/calibration-sessions", headers=headers, params=params)

    def get_calibration_session(self, session_id, headers):
        return self._request("GET", f"/calibration-sessions/{session_id}", headers=headers)

    def balance_session(self, session_id, headers):
        return self._request("POST", f"/calibration-sessions/{session_id}/balance", {}, headers)

    def finalize_session(self, session_id, headers):
        return self._request("POST", f"/calibration-sessions/{session_id}/finalize", {}, headers)

    # ---- CompPlan ----
    def create_comp_plan(self, payload, headers):
        return self._request("POST", "/comp-plans", payload, headers)

    def list_comp_plans(self, headers, params=None):
        return self._request("GET", "/comp-plans", headers=headers, params=params)

    def get_comp_plan(self, plan_id, headers):
        return self._request("GET", f"/comp-plans/{plan_id}", headers=headers)

    def recompute_comp_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/comp-plans/{plan_id}/recompute", payload, headers)

    def propose_comp_plan(self, plan_id, headers):
        return self._request("POST", f"/comp-plans/{plan_id}/propose", {}, headers)

    def approve_comp_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/comp-plans/{plan_id}/approve", payload, headers)

    def reject_comp_plan(self, plan_id, headers):
        return self._request("POST", f"/comp-plans/{plan_id}/reject", {}, headers)

    # ---- PipCase ----
    def list_review_pip_cases(self, review_id, headers, params=None):
        return self._request("GET", f"/reviews/{review_id}/pip-cases", headers=headers, params=params)

    def list_pip_cases(self, headers, params=None):
        return self._request("GET", "/pip-cases", headers=headers, params=params)

    def get_pip_case(self, pip_id, headers):
        return self._request("GET", f"/pip-cases/{pip_id}", headers=headers)

    def activate_pip_case(self, pip_id, payload, headers):
        return self._request("POST", f"/pip-cases/{pip_id}/activate", payload, headers)

    def assess_pip_case(self, pip_id, payload, headers):
        return self._request("POST", f"/pip-cases/{pip_id}/assess", payload, headers)


api_client = ApiClient()
