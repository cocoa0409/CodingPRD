"""One client method per endpoint declared by the PRD.

Every method returns the raw response so tests can assert status codes and
error envelopes. Timestamps returned by the API are left untouched; helpers in
assertions.py canonicalise them when comparing.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ audit programs
    def create_audit_program(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/audit-programs", payload, headers)

    def get_audit_program(self, program_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/audit-programs/{program_id}", None, headers)

    # --------------------------------------------------------- protocol versions
    def create_protocol_version(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/audit-programs/{program_id}/protocol-versions", payload, headers
        )

    def list_protocol_versions(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/audit-programs/{program_id}/protocol-versions", params, headers
        )

    def get_protocol_version(self, version_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/protocol-versions/{version_id}", None, headers)

    def approve_protocol_version(
        self, version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/protocol-versions/{version_id}/approve", payload, headers
        )

    # --------------------------------------------------------- protocol rollouts
    def create_rollout(
        self, version_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/protocol-versions/{version_id}/rollouts", payload, headers
        )

    def list_rollouts(
        self, version_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/protocol-versions/{version_id}/rollouts", params, headers
        )

    def list_sessions_for_version(
        self, version_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/protocol-versions/{version_id}/retraining-sessions", params, headers
        )

    def go_live(self, rollout_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/protocol-rollouts/{rollout_id}/go-live", payload, headers
        )

    # ---------------------------------------------------------------- dispatchers
    def create_dispatcher(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/dispatchers", payload, headers)

    def get_dispatcher(self, dispatcher_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/dispatchers/{dispatcher_id}", None, headers)

    def list_dispatchers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/dispatchers", params, headers)

    def certify_dispatcher(
        self, dispatcher_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dispatchers/{dispatcher_id}/certify", payload, headers
        )

    # --------------------------------------------------------------- call records
    def create_call_record(
        self, dispatcher_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/dispatchers/{dispatcher_id}/call-records", payload, headers
        )

    def list_call_records(
        self, dispatcher_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/dispatchers/{dispatcher_id}/call-records", params, headers
        )

    # ------------------------------------------------------------ sampling periods
    def create_sampling_period(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/audit-programs/{program_id}/sampling-periods", payload, headers
        )

    def list_sampling_periods(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/audit-programs/{program_id}/sampling-periods", params, headers
        )

    def draw_random_sample(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sampling-periods/{period_id}/draw-random-sample", payload, headers
        )

    def target_review(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sampling-periods/{period_id}/target-review", payload, headers
        )

    def close_sampling_period(
        self, period_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/sampling-periods/{period_id}/close", payload, headers
        )

    # -------------------------------------------------------------------- reviews
    def get_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reviews/{review_id}", None, headers)

    def list_reviews(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/reviews", params, headers)

    def submit_scores(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/reviews/{review_id}/scores", payload, headers)

    def list_score_sheets(
        self, review_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/reviews/{review_id}/score-sheets", params, headers)

    def create_rebuttal(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/reviews/{review_id}/rebuttals", payload, headers)

    def list_rebuttals(
        self, review_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", f"/reviews/{review_id}/rebuttals", params, headers)

    def decide_rebuttal(
        self, rebuttal_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/rebuttals/{rebuttal_id}/decide", payload, headers)

    def finalize_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/reviews/{review_id}/finalize", payload, headers)

    def void_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/reviews/{review_id}/void", payload, headers)

    # --------------------------------------------------------- high-risk reviews
    def create_high_risk_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/reviews/{review_id}/high-risk-reviews", payload, headers
        )

    def list_high_risk_reviews(
        self, review_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/reviews/{review_id}/high-risk-reviews", params, headers
        )

    def score_dacpr(
        self, high_risk_review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/high-risk-reviews/{high_risk_review_id}/score-dacpr", payload, headers
        )

    def sign_off_high_risk_review(
        self, high_risk_review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/high-risk-reviews/{high_risk_review_id}/sign-off", payload, headers
        )

    # --------------------------------------------------------------- coaching plans
    def create_coaching_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/coaching-plans", payload, headers)

    def get_coaching_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/coaching-plans/{plan_id}", None, headers)

    def list_coaching_plans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/coaching-plans", params, headers)

    # ----------------------------------------------------------- retraining sessions
    def create_retraining_session(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/coaching-plans/{plan_id}/retraining-sessions", payload, headers
        )

    def list_retraining_sessions(
        self, plan_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/coaching-plans/{plan_id}/retraining-sessions", params, headers
        )

    def complete_retraining_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/retraining-sessions/{session_id}/complete", payload, headers
        )

    def cancel_retraining_session(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/retraining-sessions/{session_id}/cancel", payload, headers
        )

    # ------------------------------------------------------- accreditation reports
    def create_accreditation_report(
        self, program_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/audit-programs/{program_id}/accreditation-reports", payload, headers
        )

    def list_accreditation_reports(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/audit-programs/{program_id}/accreditation-reports", params, headers
        )

    def submit_accreditation_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/accreditation-reports/{report_id}/submit", payload, headers
        )

    # ------------------------------------------------------------- logical clock
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
