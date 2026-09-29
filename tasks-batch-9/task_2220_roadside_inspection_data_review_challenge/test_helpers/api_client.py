"""Typed HTTP client: one method per endpoint of the roadside inspection API (PRD 4).

Every method returns the raw `requests.Response` so tests can assert status codes
and error envelopes themselves.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per row of the PRD 4 endpoint table."""

    # ------------------------------------------------------------------
    # Logical clock and scoring epoch
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def create_scoring_run(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/scoring-runs", payload, headers)

    def get_scoring_run(
        self, run_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/scoring-runs/{run_id}", None, headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/carriers", payload, headers)

    def list_carriers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/carriers", params, headers)

    def get_carrier(self, carrier_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/carriers/{carrier_id}", None, headers)

    def issue_fitness_determination(
        self, carrier_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/carriers/{carrier_id}/fitness-determination", payload, headers
        )

    def get_screening_risk(
        self, carrier_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/carriers/{carrier_id}/screening-risk", None, headers
        )

    # ------------------------------------------------------------------
    # Drivers
    # ------------------------------------------------------------------
    def create_driver(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/drivers", payload, headers)

    def list_drivers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/drivers", params, headers)

    def get_driver(self, driver_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/drivers/{driver_id}", None, headers)

    def patch_driver(
        self, driver_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/drivers/{driver_id}", payload, headers)

    def get_attribution_summary(
        self, driver_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/drivers/{driver_id}/attribution-summary", None, headers
        )

    # ------------------------------------------------------------------
    # Violation codes
    # ------------------------------------------------------------------
    def create_violation_code(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/violation-codes", payload, headers)

    def list_violation_codes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/violation-codes", params, headers)

    def get_violation_code(
        self, code_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/violation-codes/{code_id}", None, headers)

    def patch_violation_code(
        self, code_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/violation-codes/{code_id}", payload, headers)

    # ------------------------------------------------------------------
    # Intervention thresholds
    # ------------------------------------------------------------------
    def create_intervention_threshold(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/intervention-thresholds", payload, headers)

    def list_intervention_thresholds(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/intervention-thresholds", params, headers)

    # ------------------------------------------------------------------
    # BASIC scores
    # ------------------------------------------------------------------
    def list_basic_scores(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/basic-scores", params, headers)

    def get_basic_score(
        self, score_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/basic-scores/{score_id}", None, headers)

    # ------------------------------------------------------------------
    # Inspection reports
    # ------------------------------------------------------------------
    def create_inspection_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/inspection-reports", payload, headers)

    def list_inspection_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/inspection-reports", params, headers)

    def get_inspection_report(
        self, report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/inspection-reports/{report_id}", None, headers)

    def add_violation(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/inspection-reports/{report_id}/violations", payload, headers
        )

    def validate_report(
        self, report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/inspection-reports/{report_id}/validate", {}, headers
        )

    def score_report(
        self, report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/inspection-reports/{report_id}/score", {}, headers
        )

    def create_amendment(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/inspection-reports/{report_id}/amendments", payload, headers
        )

    def list_report_amendments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/report-amendments", params, headers)

    def get_report_amendment(
        self, amendment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/report-amendments/{amendment_id}", None, headers)

    # ------------------------------------------------------------------
    # Violations
    # ------------------------------------------------------------------
    def list_violations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/violations", params, headers)

    def get_violation(
        self, violation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/violations/{violation_id}", None, headers)

    def attribute_driver(
        self, violation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/violations/{violation_id}/driver-attribution", payload, headers
        )

    def clear_driver_attribution(
        self, violation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "DELETE", f"/violations/{violation_id}/driver-attribution", None, headers
        )

    # ------------------------------------------------------------------
    # Data challenges
    # ------------------------------------------------------------------
    def create_data_challenge(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/data-challenges", payload, headers)

    def list_data_challenges(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/data-challenges", params, headers)

    def get_data_challenge(
        self, challenge_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/data-challenges/{challenge_id}", None, headers)

    def add_evidence(
        self, challenge_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/data-challenges/{challenge_id}/evidence", payload, headers
        )

    def list_evidence(
        self, challenge_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/data-challenges/{challenge_id}/evidence", params, headers
        )

    def submit_challenge(
        self, challenge_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/data-challenges/{challenge_id}/submit", {}, headers
        )

    def withdraw_challenge(
        self, challenge_id: str, headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/data-challenges/{challenge_id}/withdraw", payload or {}, headers
        )

    def review_challenge(
        self, challenge_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/data-challenges/{challenge_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Citation adjudications
    # ------------------------------------------------------------------
    def create_citation_adjudication(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/citation-adjudications", payload, headers)

    def list_citation_adjudications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/citation-adjudications", params, headers)

    def get_citation_adjudication(
        self, adjudication_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/citation-adjudications/{adjudication_id}", None, headers
        )

    def record_court_result(
        self, adjudication_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/citation-adjudications/{adjudication_id}/court-result",
            payload,
            headers,
        )

    def apply_to_record(
        self, adjudication_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/citation-adjudications/{adjudication_id}/apply-to-record",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Coaching assignments
    # ------------------------------------------------------------------
    def create_coaching_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/coaching-assignments", payload, headers)

    def list_coaching_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/coaching-assignments", params, headers)

    def get_coaching_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/coaching-assignments/{assignment_id}", None, headers
        )

    def start_coaching(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coaching-assignments/{assignment_id}/start", {}, headers
        )

    def complete_coaching(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/coaching-assignments/{assignment_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Corrective action plans
    # ------------------------------------------------------------------
    def create_corrective_action_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/corrective-action-plans", payload, headers)

    def list_corrective_action_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/corrective-action-plans", params, headers)

    def get_corrective_action_plan(
        self, cap_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/corrective-action-plans/{cap_id}", None, headers)

    def add_action_item(
        self, cap_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/action-items", payload, headers
        )

    def list_action_items(
        self, cap_id: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/corrective-action-plans/{cap_id}/action-items", params, headers
        )

    def set_action_item_status(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/cap-action-items/{item_id}/status", payload, headers
        )

    def submit_cap(self, cap_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/submit", {}, headers
        )

    def review_cap(
        self, cap_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/reviews", payload, headers
        )

    def decide_cap(
        self, cap_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-action-plans/{cap_id}/decision", payload, headers
        )

    # ------------------------------------------------------------------
    # Raw helpers for negative tests that must bypass the typed surface
    # ------------------------------------------------------------------
    def raw_post(
        self, path: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", path, payload, headers)

    def raw_get(
        self, path: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", path, params, headers)

    def raw_patch(
        self, path: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", path, payload, headers)

    def raw_delete(
        self, path: str, headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("DELETE", path, params, headers)
