"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601: str, headers: Dict):
        return self._request(
            "POST", "/v1/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- cases ---
    def create_case(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict):
        return self._request("GET", f"/v1/cases/{case_id}", headers=headers)

    def discharge_case(self, case_id: str, headers: Dict):
        return self._request("POST", f"/v1/cases/{case_id}/discharge", {}, headers)

    def list_case_assets(self, case_id: str, headers: Dict,
                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/cases/{case_id}/assets", headers=headers, params=params,
        )

    def list_case_engagements(self, case_id: str, headers: Dict,
                              params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/cases/{case_id}/engagements", headers=headers, params=params,
        )

    def list_case_authorization_requests(self, case_id: str, headers: Dict,
                                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/cases/{case_id}/authorization-requests",
            headers=headers, params=params,
        )

    def list_case_status_reports(self, case_id: str, headers: Dict,
                                 params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/cases/{case_id}/status-reports",
            headers=headers, params=params,
        )

    # --- assets ---
    def create_asset(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/assets", payload, headers)

    def get_asset(self, asset_id: str, headers: Dict):
        return self._request("GET", f"/v1/assets/{asset_id}", headers=headers)

    def liquidate_asset(self, asset_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/assets/{asset_id}/liquidate", payload, headers,
        )

    def abandon_asset(self, asset_id: str, payload: Optional[Dict], headers: Dict):
        return self._request(
            "POST", f"/v1/assets/{asset_id}/abandon", payload or {}, headers,
        )

    def list_asset_authorization_requests(self, asset_id: str, headers: Dict,
                                          params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/assets/{asset_id}/authorization-requests",
            headers=headers, params=params,
        )

    # --- claims ---
    def create_claim(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/claims", payload, headers)

    def list_claims(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/v1/claims", headers=headers, params=params)

    def get_claim(self, claim_id: str, headers: Dict):
        return self._request("GET", f"/v1/claims/{claim_id}", headers=headers)

    def determine_claim(self, claim_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/claims/{claim_id}/determine", payload, headers,
        )

    def reconsider_claim(self, claim_id: str, headers: Dict):
        return self._request("POST", f"/v1/claims/{claim_id}/reconsider", {}, headers)

    def list_claim_payments(self, claim_id: str, headers: Dict,
                            params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/claims/{claim_id}/payments", headers=headers, params=params,
        )

    # --- engagements ---
    def create_engagement(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/engagements", payload, headers)

    def get_engagement(self, engagement_id: str, headers: Dict):
        return self._request(
            "GET", f"/v1/engagements/{engagement_id}", headers=headers,
        )

    def decide_engagement(self, engagement_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/engagements/{engagement_id}/decide", payload, headers,
        )

    def list_engagement_fee_applications(self, engagement_id: str, headers: Dict,
                                         params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/engagements/{engagement_id}/fee-applications",
            headers=headers, params=params,
        )

    # --- fee applications ---
    def create_fee_application(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/fee-applications", payload, headers)

    def decide_fee_application(self, application_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/fee-applications/{application_id}/decide", payload, headers,
        )

    def pay_fee_application(self, application_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/fee-applications/{application_id}/pay", payload, headers,
        )

    # --- authorization requests ---
    def create_authorization_request(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/authorization-requests", payload, headers)

    def decide_authorization_request(self, request_id: str, payload: Dict,
                                     headers: Dict):
        return self._request(
            "POST", f"/v1/authorization-requests/{request_id}/decide",
            payload, headers,
        )

    # --- status reports ---
    def create_status_report(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/status-reports", payload, headers)

    def decide_status_report(self, report_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/status-reports/{report_id}/decide", payload, headers,
        )

    # --- distribution plans ---
    def create_distribution_plan(self, payload: Dict, headers: Dict):
        return self._request("POST", "/v1/distribution-plans", payload, headers)

    def list_distribution_plans(self, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", "/v1/distribution-plans", headers=headers, params=params,
        )

    def get_distribution_plan(self, plan_id: str, headers: Dict):
        return self._request(
            "GET", f"/v1/distribution-plans/{plan_id}", headers=headers,
        )

    def decide_distribution_plan(self, plan_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/distribution-plans/{plan_id}/decide", payload, headers,
        )

    def amend_distribution_plan(self, plan_id: str, payload: Optional[Dict],
                                headers: Dict):
        return self._request(
            "POST", f"/v1/distribution-plans/{plan_id}/amend",
            payload or {}, headers,
        )

    def list_plan_payments(self, plan_id: str, headers: Dict,
                           params: Optional[Dict] = None):
        return self._request(
            "GET", f"/v1/distribution-plans/{plan_id}/payments",
            headers=headers, params=params,
        )

    # --- distribution payments ---
    def pay_distribution_payment(self, payment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/v1/distribution-payments/{payment_id}/pay", payload, headers,
        )

    def void_distribution_payment(self, payment_id: str, headers: Dict):
        return self._request(
            "POST", f"/v1/distribution-payments/{payment_id}/void", {}, headers,
        )


api_client = ApiClient()
