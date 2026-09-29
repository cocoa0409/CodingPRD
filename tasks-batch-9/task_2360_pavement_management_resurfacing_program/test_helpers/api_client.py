"""Typed HTTP client for the Pavement Management & Resurfacing Program API.

One method per endpoint declared in the PRD's endpoint table. Every method
returns the raw ``requests.Response`` so tests can assert on status codes as
well as bodies.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/pavement"


class PavementApiClient(GenericApiClient):
    """Endpoint surface of the pavement program API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Network segments
    # ------------------------------------------------------------------
    def create_segment(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/segments", payload, headers)

    def get_segment(self, segment_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/segments/{segment_id}", None, headers)

    def list_segments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/segments", params, headers)

    # ------------------------------------------------------------------
    # Condition surveys
    # ------------------------------------------------------------------
    def create_survey(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/condition-surveys", payload, headers)

    def get_survey(self, survey_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/condition-surveys/{survey_id}", None, headers)

    def list_surveys(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/condition-surveys", params, headers)

    def seal_survey(
        self, survey_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/condition-surveys/{survey_id}/seal", payload or {}, headers
        )

    def generate_candidates(
        self, survey_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/condition-surveys/{survey_id}/generate-candidates",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Distress observations
    # ------------------------------------------------------------------
    def create_observation(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/distress-observations", payload, headers)

    def get_observation(
        self, observation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/distress-observations/{observation_id}", None, headers
        )

    def list_observations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/distress-observations", params, headers)

    def qc_observation(
        self, observation_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/distress-observations/{observation_id}/qc", payload, headers
        )

    # ------------------------------------------------------------------
    # Treatment candidates
    # ------------------------------------------------------------------
    def get_candidate(self, candidate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/treatment-candidates/{candidate_id}", None, headers
        )

    def list_candidates(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/treatment-candidates", params, headers)

    def override_candidate(
        self, candidate_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/treatment-candidates/{candidate_id}/override", payload, headers
        )

    # ------------------------------------------------------------------
    # Budget scenarios
    # ------------------------------------------------------------------
    def create_scenario(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/budget-scenarios", payload, headers)

    def get_scenario(self, scenario_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/budget-scenarios/{scenario_id}", None, headers)

    def list_scenarios(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/budget-scenarios", params, headers)

    def run_scenario(
        self, scenario_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/budget-scenarios/{scenario_id}/run", payload or {}, headers
        )

    def adopt_scenario(
        self, scenario_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/budget-scenarios/{scenario_id}/adopt", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Scenario allocations
    # ------------------------------------------------------------------
    def create_allocation(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/scenario-allocations", payload, headers)

    def get_allocation(
        self, allocation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/scenario-allocations/{allocation_id}", None, headers
        )

    def list_allocations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/scenario-allocations", params, headers)

    # ------------------------------------------------------------------
    # Contractors
    # ------------------------------------------------------------------
    def create_contractor(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/contractors", payload, headers)

    def get_contractor(
        self, contractor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/contractors/{contractor_id}", None, headers)

    def list_contractors(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/contractors", params, headers)

    def get_contractor_scorecard(
        self, contractor_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/contractors/{contractor_id}/scorecard", None, headers
        )

    # ------------------------------------------------------------------
    # Resurfacing projects
    # ------------------------------------------------------------------
    def create_project(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/projects", payload, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/projects/{project_id}", None, headers)

    def list_projects(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/projects", params, headers)

    def advance_project(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/projects/{project_id}/advance", payload, headers)

    def award_project(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/projects/{project_id}/award", payload, headers)

    def cancel_award(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/projects/{project_id}/cancel-award", payload, headers
        )

    def substantial_completion(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/projects/{project_id}/substantial-completion", payload, headers
        )

    def accept_project(
        self, project_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/projects/{project_id}/accept", payload, headers)

    # ------------------------------------------------------------------
    # Project segments (lines)
    # ------------------------------------------------------------------
    def create_project_segment(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/project-segments", payload, headers)

    def get_project_segment(self, line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/project-segments/{line_id}", None, headers)

    def list_project_segments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/project-segments", params, headers)

    def delete_project_segment(
        self, line_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "DELETE", f"{BASE}/project-segments/{line_id}", payload, headers
        )

    def notice(
        self, line_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/project-segments/{line_id}/notice", payload, headers
        )

    # ------------------------------------------------------------------
    # Utility coordinations
    # ------------------------------------------------------------------
    def get_coordination(
        self, coordination_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/utility-coordinations/{coordination_id}", None, headers
        )

    def list_coordinations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/utility-coordinations", params, headers)

    def respond_coordination(
        self, coordination_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/utility-coordinations/{coordination_id}/respond", payload, headers
        )

    def complete_coordination_work(
        self, coordination_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/utility-coordinations/{coordination_id}/complete-work",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Cut permits
    # ------------------------------------------------------------------
    def create_cut_permit(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{BASE}/cut-permits", payload, headers)

    def get_cut_permit(self, permit_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/cut-permits/{permit_id}", None, headers)

    def list_cut_permits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/cut-permits", params, headers)

    def decide_cut_permit(
        self, permit_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/cut-permits/{permit_id}/decide", payload, headers
        )

    def complete_cut(
        self, permit_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/cut-permits/{permit_id}/complete-cut", payload, headers
        )

    # ------------------------------------------------------------------
    # Acceptance tests
    # ------------------------------------------------------------------
    def create_acceptance_test(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/acceptance-tests", payload, headers)

    def get_acceptance_test(self, test_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{BASE}/acceptance-tests/{test_id}", None, headers)

    def list_acceptance_tests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/acceptance-tests", params, headers)

    def decide_acceptance_test(
        self, test_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/acceptance-tests/{test_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Service requests
    # ------------------------------------------------------------------
    def create_service_request(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/service-requests", payload, headers)

    def get_service_request(
        self, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/service-requests/{request_id}", None, headers)

    def list_service_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/service-requests", params, headers)

    def triage_service_request(
        self, request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/service-requests/{request_id}/triage", payload, headers
        )

    def close_service_request(
        self, request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/service-requests/{request_id}/close", payload, headers
        )
