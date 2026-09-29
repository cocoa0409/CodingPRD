"""
API client for the Qualified Opportunity Fund compliance API.

One method per endpoint the PRD declares, all under the `/qof` prefix. Every
method returns the raw `requests.Response` so tests can assert both the status
code and the envelope.

List methods take `params` for pagination and filters; the framework client
forwards them as query parameters.
"""

from typing import Any, Dict, List, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """Endpoint-per-method client for the QOF compliance API."""

    # ------------------------------------------------------------------
    # Logical clock and ops runs
    # ------------------------------------------------------------------

    def set_clock(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    def get_clock(
        self, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/_clock", None, headers)

    def run_deadline_sweep(
        self,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/ops-runs/deadline-sweep", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Investor
    # ------------------------------------------------------------------

    def create_investor(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/investors", payload, headers)

    def get_investor(
        self, investor_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/investors/{investor_id}", None, headers
        )

    def list_investors(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/investors", params, headers)

    def patch_investor_attestation(
        self,
        investor_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/investors/{investor_id}/attestation",
            payload,
            headers,
        )

    def get_investor_statement(
        self, investor_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/investors/{investor_id}/statement", None, headers
        )

    def list_investor_eligible_gains(
        self,
        investor_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/investors/{investor_id}/eligible-gains",
            params,
            headers,
        )

    def list_investor_deferral_elections(
        self,
        investor_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/investors/{investor_id}/deferral-elections",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # Fund
    # ------------------------------------------------------------------

    def create_fund(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/funds", payload, headers)

    def get_fund(
        self, fund_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/funds/{fund_id}", None, headers)

    def list_funds(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/funds", params, headers)

    def self_certify_fund(
        self,
        fund_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/funds/{fund_id}/self-certify", payload, headers
        )

    def decertify_fund(
        self,
        fund_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/funds/{fund_id}/decertify", payload or {}, headers
        )

    def create_asset_test(
        self,
        fund_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/funds/{fund_id}/asset-tests", payload, headers
        )

    def list_fund_asset_tests(
        self,
        fund_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/funds/{fund_id}/asset-tests", params, headers
        )

    # ------------------------------------------------------------------
    # EligibleGain
    # ------------------------------------------------------------------

    def create_eligible_gain(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/eligible-gains", payload, headers)

    def get_eligible_gain(
        self, gain_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/eligible-gains/{gain_id}", None, headers
        )

    def list_eligible_gains(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/eligible-gains", params, headers)

    def list_gain_deferral_elections(
        self,
        gain_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/eligible-gains/{gain_id}/deferral-elections",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # DeferralElection
    # ------------------------------------------------------------------

    def create_deferral_election(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/deferral-elections", payload, headers
        )

    def get_deferral_election(
        self, election_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/deferral-elections/{election_id}", None, headers
        )

    def list_deferral_elections(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/deferral-elections", params, headers
        )

    def revoke_deferral_election(
        self,
        election_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/deferral-elections/{election_id}/revoke",
            payload,
            headers,
        )

    def create_inclusion_event(
        self,
        election_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/deferral-elections/{election_id}/inclusion-events",
            payload,
            headers,
        )

    def list_inclusion_events(
        self,
        election_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/deferral-elections/{election_id}/inclusion-events",
            params,
            headers,
        )

    def create_step_up_election(
        self,
        election_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/deferral-elections/{election_id}/step-up-elections",
            payload,
            headers,
        )

    def list_step_up_elections(
        self,
        election_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/deferral-elections/{election_id}/step-up-elections",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # FundAsset
    # ------------------------------------------------------------------

    def create_fund_asset(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fund-assets", payload, headers)

    def get_fund_asset(
        self, asset_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/fund-assets/{asset_id}", None, headers
        )

    def list_fund_assets(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fund-assets", params, headers)

    def dispose_fund_asset(
        self,
        asset_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fund-assets/{asset_id}/dispose", payload, headers
        )

    # ------------------------------------------------------------------
    # QOZBusiness
    # ------------------------------------------------------------------

    def create_qoz_business(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/qoz-businesses", payload, headers)

    def get_qoz_business(
        self, business_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/qoz-businesses/{business_id}", None, headers
        )

    def list_qoz_businesses(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/qoz-businesses", params, headers)

    def patch_qoz_business_reported_figures(
        self,
        business_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"{API_PREFIX}/qoz-businesses/{business_id}/reported-figures",
            payload,
            headers,
        )

    def create_business_test(
        self,
        business_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/qoz-businesses/{business_id}/business-tests",
            payload,
            headers,
        )

    def list_business_tests(
        self,
        business_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/qoz-businesses/{business_id}/business-tests",
            params,
            headers,
        )

    # ------------------------------------------------------------------
    # BusinessTest
    # ------------------------------------------------------------------

    def get_business_test(
        self, test_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/business-tests/{test_id}", None, headers
        )

    def measure_business_test(
        self,
        test_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/business-tests/{test_id}/measure", payload, headers
        )

    def certify_business_test(
        self,
        test_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/business-tests/{test_id}/certify",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # AssetTest
    # ------------------------------------------------------------------

    def get_asset_test(
        self, test_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/asset-tests/{test_id}", None, headers
        )

    def measure_asset_test(
        self,
        test_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/asset-tests/{test_id}/measure",
            payload or {},
            headers,
        )

    def certify_asset_test(
        self,
        test_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/asset-tests/{test_id}/certify",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # ImprovementProject
    # ------------------------------------------------------------------

    def create_improvement_project(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/improvement-projects", payload, headers
        )

    def get_improvement_project(
        self, project_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/improvement-projects/{project_id}", None, headers
        )

    def list_improvement_projects(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/improvement-projects", params, headers
        )

    def create_project_expenditure(
        self,
        project_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/improvement-projects/{project_id}/expenditures",
            payload,
            headers,
        )

    def list_project_expenditures(
        self,
        project_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/improvement-projects/{project_id}/expenditures",
            params,
            headers,
        )

    def evaluate_improvement_project(
        self,
        project_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/improvement-projects/{project_id}/evaluate",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # WorkingCapitalPlan
    # ------------------------------------------------------------------

    def create_wcsh_plan(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/wcsh-plans", payload, headers)

    def get_wcsh_plan(
        self, plan_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/wcsh-plans/{plan_id}", None, headers
        )

    def list_wcsh_plans(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/wcsh-plans", params, headers)

    def activate_wcsh_plan(
        self,
        plan_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/wcsh-plans/{plan_id}/activate",
            payload or {},
            headers,
        )

    def create_wcsh_expenditure(
        self,
        plan_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/wcsh-plans/{plan_id}/expenditures", payload, headers
        )

    def list_wcsh_expenditures(
        self,
        plan_id: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/wcsh-plans/{plan_id}/expenditures", params, headers
        )

    def evaluate_wcsh_checkpoint(
        self,
        plan_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/wcsh-plans/{plan_id}/evaluate-checkpoint",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # PenaltyAssessment
    # ------------------------------------------------------------------

    def get_penalty_assessment(
        self, assessment_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/penalty-assessments/{assessment_id}", None, headers
        )

    def list_penalty_assessments(
        self,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/penalty-assessments", params, headers
        )

    def create_cure_request(
        self,
        assessment_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/penalty-assessments/{assessment_id}/cure-requests",
            payload,
            headers,
        )

    def create_cure_decision(
        self,
        assessment_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/penalty-assessments/{assessment_id}/cure-decisions",
            payload,
            headers,
        )


# Module-level singleton the conftest session fixture exposes as `api`.
api_client = ApiClient()
