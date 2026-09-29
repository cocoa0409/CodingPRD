"""One method per endpoint of PRD 4, all mounted under the `/resilience` prefix.

The client adds nothing but URL construction: every method forwards the caller's
headers untouched so that the tests can exercise the authentication and
authorization ladder of PRD 2.1 directly, including calls with no headers at all.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/resilience"


class ApiClient(GenericApiClient):
    """Thin, PRD-shaped façade over the generic HTTP client."""

    # -- raw escape hatches -------------------------------------------------

    def patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("PATCH", path, payload=json, headers=headers)

    def raw_get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", path, headers=headers, params=params)

    # -- jurisdictions ------------------------------------------------------

    def create_jurisdiction(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/jurisdictions", json=payload, headers=headers)

    def list_jurisdictions(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/jurisdictions", headers=headers, params=params)

    def get_jurisdiction(self, jurisdiction_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/jurisdictions/{jurisdiction_id}", headers=headers)

    def patch_jurisdiction(self, jurisdiction_id, payload, headers=None) -> requests.Response:
        return self.patch(
            f"{BASE}/jurisdictions/{jurisdiction_id}", json=payload, headers=headers
        )

    # -- plan cycles --------------------------------------------------------

    def create_plan_cycle(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/plan-cycles", json=payload, headers=headers)

    def list_plan_cycles(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/plan-cycles", headers=headers, params=params)

    def get_plan_cycle(self, plan_cycle_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/plan-cycles/{plan_cycle_id}", headers=headers)

    def open_engagement(self, plan_cycle_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/plan-cycles/{plan_cycle_id}/open-engagement",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def open_endorsement_round(self, plan_cycle_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/plan-cycles/{plan_cycle_id}/open-endorsement-round",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def close_endorsement_round(self, plan_cycle_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/plan-cycles/{plan_cycle_id}/close-endorsement-round",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def get_endorsement_tally(self, plan_cycle_id, headers=None) -> requests.Response:
        return self.get(
            f"{BASE}/plan-cycles/{plan_cycle_id}/endorsement-tally", headers=headers
        )

    # -- hazard profiles ----------------------------------------------------

    def create_hazard_profile(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/hazard-profiles", json=payload, headers=headers)

    def list_hazard_profiles(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/hazard-profiles", headers=headers, params=params)

    def get_hazard_profile(self, hazard_profile_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/hazard-profiles/{hazard_profile_id}", headers=headers)

    def publish_hazard_profile(self, hazard_profile_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/hazard-profiles/{hazard_profile_id}/publish",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def revise_hazard_profile(self, hazard_profile_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/hazard-profiles/{hazard_profile_id}/revisions",
            json=payload,
            headers=headers,
        )

    # -- lifeline assets ----------------------------------------------------

    def create_asset(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/assets", json=payload, headers=headers)

    def list_assets(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/assets/{asset_id}", headers=headers)

    def patch_asset(self, asset_id, payload, headers=None) -> requests.Response:
        return self.patch(f"{BASE}/assets/{asset_id}", json=payload, headers=headers)

    def rank_asset(self, asset_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/assets/{asset_id}/criticality-ranking",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # -- vulnerability assessments -----------------------------------------

    def create_assessment(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/vulnerability-assessments", json=payload, headers=headers)

    def list_assessments(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/vulnerability-assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/vulnerability-assessments/{assessment_id}", headers=headers)

    def assess(self, assessment_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/vulnerability-assessments/{assessment_id}/assess",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # -- adaptation projects ------------------------------------------------

    def create_project(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/projects", json=payload, headers=headers)

    def list_projects(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/projects/{project_id}", headers=headers)

    def patch_project(self, project_id, payload, headers=None) -> requests.Response:
        return self.patch(f"{BASE}/projects/{project_id}", json=payload, headers=headers)

    def screen_project(self, project_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/screen",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def create_asset_link(self, project_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/asset-links", json=payload, headers=headers
        )

    def list_asset_links(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/asset-links", headers=headers, params=params)

    def get_asset_link(self, link_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/asset-links/{link_id}", headers=headers)

    def create_analysis(self, project_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/analyses", json=payload, headers=headers
        )

    def list_analyses(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/analyses", headers=headers, params=params)

    def get_analysis(self, analysis_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/analyses/{analysis_id}", headers=headers)

    def certify_analysis(self, analysis_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/analyses/{analysis_id}/certify",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def reject_analysis(self, analysis_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/analyses/{analysis_id}/reject",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def withdraw_project(self, project_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/withdraw",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def submit_grant(self, project_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/grant-submission", json=payload, headers=headers
        )

    def award_grant(self, project_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/grant-award",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def grant_equity_waiver(self, project_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/equity-waiver", json=payload, headers=headers
        )

    def report_indicator(self, project_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/projects/{project_id}/indicator-reports", json=payload, headers=headers
        )

    # -- capital programs ---------------------------------------------------

    def create_capital_program(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/capital-programs", json=payload, headers=headers)

    def list_capital_programs(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/capital-programs", headers=headers, params=params)

    def get_capital_program(self, program_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/capital-programs/{program_id}", headers=headers)

    def allocate(self, program_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/capital-programs/{program_id}/allocations", json=payload, headers=headers
        )

    # -- engagement sessions ------------------------------------------------

    def create_engagement_session(self, plan_cycle_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/plan-cycles/{plan_cycle_id}/engagement-sessions",
            json=payload,
            headers=headers,
        )

    def list_engagement_sessions(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/engagement-sessions", headers=headers, params=params)

    def get_engagement_session(self, session_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/engagement-sessions/{session_id}", headers=headers)

    def complete_engagement_session(self, session_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/engagement-sessions/{session_id}/complete", json=payload, headers=headers
        )

    # -- endorsements -------------------------------------------------------

    def cast_endorsement(self, plan_cycle_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/plan-cycles/{plan_cycle_id}/endorsements", json=payload, headers=headers
        )

    def list_endorsements(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/endorsements", headers=headers, params=params)

    def get_endorsement(self, endorsement_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/endorsements/{endorsement_id}", headers=headers)

    # -- mutual aid ---------------------------------------------------------

    def create_pact(self, payload, headers=None) -> requests.Response:
        return self.post(f"{BASE}/mutual-aid-pacts", json=payload, headers=headers)

    def list_pacts(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/mutual-aid-pacts", headers=headers, params=params)

    def get_pact(self, pact_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/mutual-aid-pacts/{pact_id}", headers=headers)

    def create_commitment(self, pact_id, payload, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/mutual-aid-pacts/{pact_id}/commitments", json=payload, headers=headers
        )

    def list_commitments(self, headers=None, params=None) -> requests.Response:
        return self.get(f"{BASE}/mutual-aid-commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id, headers=None) -> requests.Response:
        return self.get(f"{BASE}/mutual-aid-commitments/{commitment_id}", headers=headers)

    def release_commitment(self, commitment_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/mutual-aid-commitments/{commitment_id}/release",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def fulfill_commitment(self, commitment_id, headers=None, payload=None) -> requests.Response:
        return self.post(
            f"{BASE}/mutual-aid-commitments/{commitment_id}/fulfill",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # -- logical clock ------------------------------------------------------

    def set_clock(self, to_iso8601, headers=None) -> requests.Response:
        return self.post(
            f"{BASE}/_clock/set_current_utc",
            json={"to_iso8601": to_iso8601},
            headers=headers,
        )


api_client = ApiClient()
