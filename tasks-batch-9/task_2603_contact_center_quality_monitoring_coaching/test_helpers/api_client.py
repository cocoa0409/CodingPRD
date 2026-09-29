"""Typed HTTP client with one method per endpoint of PRD section 4.

Every path is written exactly as the endpoint table writes it, because PRD 4
states "Every endpoint below is mounted at the API root, exactly as written in
the Path column".  Every method takes an explicit `headers` mapping, since
"every request must carry the `X-User-ID` and `X-User-Role` headers".
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per row of the PRD section 4 endpoint table."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc"""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Evaluation forms
    # ------------------------------------------------------------------
    def create_form(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /evaluation-forms"""
        return self._request("POST", "/evaluation-forms", payload, headers)

    def activate_form(self, form_id: str, headers: Dict[str, str], payload: Any = None) -> requests.Response:
        """POST /evaluation-forms/{id}/activate"""
        return self._request(
            "POST", "/evaluation-forms/{}/activate".format(form_id), payload, headers
        )

    def retire_form(self, form_id: str, headers: Dict[str, str], payload: Any = None) -> requests.Response:
        """POST /evaluation-forms/{id}/retire"""
        return self._request(
            "POST", "/evaluation-forms/{}/retire".format(form_id), payload, headers
        )

    def get_form(self, form_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /evaluation-forms/{id}"""
        return self._request("GET", "/evaluation-forms/{}".format(form_id), None, headers)

    def list_form_behaviors(
        self, form_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /evaluation-forms/{id}/behaviors"""
        return self._request(
            "GET", "/evaluation-forms/{}/behaviors".format(form_id), params, headers
        )

    def list_forms(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /evaluation-forms"""
        return self._request("GET", "/evaluation-forms", params, headers)

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------
    def create_agent(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /agents"""
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /agents/{id}"""
        return self._request("GET", "/agents/{}".format(agent_id), None, headers)

    def list_agents(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /agents"""
        return self._request("GET", "/agents", params, headers)

    def get_quality_summary(self, agent_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /agents/{id}/quality-summary"""
        return self._request(
            "GET", "/agents/{}/quality-summary".format(agent_id), None, headers
        )

    def award_recognition(
        self, agent_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /agents/{id}/recognition"""
        return self._request(
            "POST", "/agents/{}/recognition".format(agent_id), payload, headers
        )

    # ------------------------------------------------------------------
    # Evaluators
    # ------------------------------------------------------------------
    def create_evaluator(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /evaluators"""
        return self._request("POST", "/evaluators", payload, headers)

    def get_evaluator(self, evaluator_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /evaluators/{id}"""
        return self._request("GET", "/evaluators/{}".format(evaluator_id), None, headers)

    def list_evaluators(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /evaluators"""
        return self._request("GET", "/evaluators", params, headers)

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------
    def create_interaction(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /interactions"""
        return self._request("POST", "/interactions", payload, headers)

    def consent_review(
        self, interaction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /interactions/{id}/consent-review"""
        return self._request(
            "POST", "/interactions/{}/consent-review".format(interaction_id), payload, headers
        )

    def get_interaction(self, interaction_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /interactions/{id}"""
        return self._request("GET", "/interactions/{}".format(interaction_id), None, headers)

    def list_interactions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /interactions"""
        return self._request("GET", "/interactions", params, headers)

    # ------------------------------------------------------------------
    # Analytics scans
    # ------------------------------------------------------------------
    def create_scan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /analytics-scans"""
        return self._request("POST", "/analytics-scans", payload, headers)

    def get_scan(self, scan_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /analytics-scans/{id}"""
        return self._request("GET", "/analytics-scans/{}".format(scan_id), None, headers)

    def list_scans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /analytics-scans"""
        return self._request("GET", "/analytics-scans", params, headers)

    # ------------------------------------------------------------------
    # Sampling plans
    # ------------------------------------------------------------------
    def create_plan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /sample-plans"""
        return self._request("POST", "/sample-plans", payload, headers)

    def open_plan(self, plan_id: str, headers: Dict[str, str], payload: Any = None) -> requests.Response:
        """POST /sample-plans/{id}/open"""
        return self._request("POST", "/sample-plans/{}/open".format(plan_id), payload, headers)

    def close_plan(self, plan_id: str, headers: Dict[str, str], payload: Any = None) -> requests.Response:
        """POST /sample-plans/{id}/close"""
        return self._request("POST", "/sample-plans/{}/close".format(plan_id), payload, headers)

    def get_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /sample-plans/{id}"""
        return self._request("GET", "/sample-plans/{}".format(plan_id), None, headers)

    def list_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /sample-plans"""
        return self._request("GET", "/sample-plans", params, headers)

    # ------------------------------------------------------------------
    # Sample selections
    # ------------------------------------------------------------------
    def create_selection(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /sample-selections"""
        return self._request("POST", "/sample-selections", payload, headers)

    def assign_selection(
        self, selection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /sample-selections/{id}/assign"""
        return self._request(
            "POST", "/sample-selections/{}/assign".format(selection_id), payload, headers
        )

    def exclude_selection(
        self, selection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /sample-selections/{id}/exclude"""
        return self._request(
            "POST", "/sample-selections/{}/exclude".format(selection_id), payload, headers
        )

    def get_selection(self, selection_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /sample-selections/{id}"""
        return self._request("GET", "/sample-selections/{}".format(selection_id), None, headers)

    def list_selections(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /sample-selections"""
        return self._request("GET", "/sample-selections", params, headers)

    # ------------------------------------------------------------------
    # Evaluations
    # ------------------------------------------------------------------
    def create_evaluation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /evaluations"""
        return self._request("POST", "/evaluations", payload, headers)

    def submit_evaluation(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /evaluations/{id}/submit"""
        return self._request(
            "POST", "/evaluations/{}/submit".format(evaluation_id), payload, headers
        )

    def deliver_evaluation(
        self, evaluation_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        """POST /evaluations/{id}/deliver"""
        return self._request(
            "POST", "/evaluations/{}/deliver".format(evaluation_id), payload, headers
        )

    def acknowledge_evaluation(
        self, evaluation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /evaluations/{id}/acknowledge"""
        return self._request(
            "POST", "/evaluations/{}/acknowledge".format(evaluation_id), payload, headers
        )

    def get_evaluation(self, evaluation_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /evaluations/{id}"""
        return self._request("GET", "/evaluations/{}".format(evaluation_id), None, headers)

    def list_evaluations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /evaluations"""
        return self._request("GET", "/evaluations", params, headers)

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /disputes"""
        return self._request("POST", "/disputes", payload, headers)

    def review_dispute(
        self, dispute_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        """POST /disputes/{id}/review"""
        return self._request("POST", "/disputes/{}/review".format(dispute_id), payload, headers)

    def resolve_dispute(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /disputes/{id}/resolve"""
        return self._request("POST", "/disputes/{}/resolve".format(dispute_id), payload, headers)

    def respond_dispute(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /disputes/{id}/respond"""
        return self._request("POST", "/disputes/{}/respond".format(dispute_id), payload, headers)

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /disputes/{id}"""
        return self._request("GET", "/disputes/{}".format(dispute_id), None, headers)

    def list_disputes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /disputes"""
        return self._request("GET", "/disputes", params, headers)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def create_session(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /calibration-sessions"""
        return self._request("POST", "/calibration-sessions", payload, headers)

    def start_scoring(
        self, session_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        """POST /calibration-sessions/{id}/start-scoring"""
        return self._request(
            "POST", "/calibration-sessions/{}/start-scoring".format(session_id), payload, headers
        )

    def create_submission(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /calibration-submissions"""
        return self._request("POST", "/calibration-submissions", payload, headers)

    def close_session(
        self, session_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        """POST /calibration-sessions/{id}/close"""
        return self._request(
            "POST", "/calibration-sessions/{}/close".format(session_id), payload, headers
        )

    def get_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /calibration-sessions/{id}"""
        return self._request("GET", "/calibration-sessions/{}".format(session_id), None, headers)

    def list_sessions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /calibration-sessions"""
        return self._request("GET", "/calibration-sessions", params, headers)

    def get_submission(self, submission_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /calibration-submissions/{id}"""
        return self._request(
            "GET", "/calibration-submissions/{}".format(submission_id), None, headers
        )

    def list_submissions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /calibration-submissions"""
        return self._request("GET", "/calibration-submissions", params, headers)

    # ------------------------------------------------------------------
    # Coaching plans
    # ------------------------------------------------------------------
    def create_coaching_plan(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        """POST /coaching-plans"""
        return self._request("POST", "/coaching-plans", payload, headers)

    def log_coaching_session(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /coaching-plans/{id}/log-session"""
        return self._request(
            "POST", "/coaching-plans/{}/log-session".format(plan_id), payload, headers
        )

    def complete_coaching_plan(
        self, plan_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        """POST /coaching-plans/{id}/complete"""
        return self._request(
            "POST", "/coaching-plans/{}/complete".format(plan_id), payload, headers
        )

    def escalate_coaching_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        """POST /coaching-plans/{id}/escalate"""
        return self._request(
            "POST", "/coaching-plans/{}/escalate".format(plan_id), payload, headers
        )

    def get_coaching_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        """GET /coaching-plans/{id}"""
        return self._request("GET", "/coaching-plans/{}".format(plan_id), None, headers)

    def list_coaching_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """GET /coaching-plans"""
        return self._request("GET", "/coaching-plans", params, headers)

    # ------------------------------------------------------------------
    # Raw escape hatch, for header-shape and undeclared-role probes.
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Send an arbitrary request, including one with no headers at all."""
        return self._request(method, path, payload, headers, params)


#: Module-level client shared by the whole suite.
api_client = ApiClient()
