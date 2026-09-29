"""
Endpoint client for the Lender Appraisal Review Desk API.

One method per endpoint of the PRD endpoint table. Every method returns the raw
HTTP response so that a test can assert on the status code as well as the body.
All paths are rooted at the ``/appraisal-desk`` prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """HTTP client exposing every endpoint of the appraisal review desk."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # ------------------------------------------------------------ loan files
    def create_loan_file(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/loan-files", payload, headers)

    def get_loan_file(self, loan_file_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/loan-files/{loan_file_id}", None, headers)

    def list_loan_files(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/loan-files", params, headers)

    def set_underwriting_status(self, loan_file_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/loan-files/{loan_file_id}/underwriting-status",
            payload, headers,
        )

    # ------------------------------------------------------------- appraisers
    def create_appraiser(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/appraisers", payload, headers)

    def get_appraiser(self, appraiser_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/appraisers/{appraiser_id}", None, headers)

    def list_appraisers(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/appraisers", params, headers)

    def panel_review(self, appraiser_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/appraisers/{appraiser_id}/panel-review", payload, headers,
        )

    # -------------------------------------------------------------------- AMCs
    def create_amc(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/amcs", payload, headers)

    def get_amc(self, amc_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/amcs/{amc_id}", None, headers)

    def list_amcs(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/amcs", params, headers)

    # ------------------------------------------------------ panel memberships
    def create_panel_membership(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/panel-memberships", payload, headers)

    def get_panel_membership(self, membership_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/panel-memberships/{membership_id}", None, headers,
        )

    def list_panel_memberships(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/panel-memberships", params, headers)

    # ------------------------------------------------------------- appraisals
    def create_appraisal(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/appraisals/{appraisal_id}", None, headers)

    def list_appraisals(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/appraisals", params, headers)

    # ------------------------------------------------------------ comparables
    def create_comparable(self, appraisal_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/appraisals/{appraisal_id}/comparables", payload, headers,
        )

    def list_comparables(self, appraisal_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/appraisals/{appraisal_id}/comparables", params, headers,
        )

    # ----------------------------------------------------------- rule checks
    def run_rule_checks(self, appraisal_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/appraisals/{appraisal_id}/run-rule-checks", payload, headers,
        )

    def list_rule_checks(self, appraisal_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/appraisals/{appraisal_id}/rule-checks", params, headers,
        )

    # ----------------------------------------------------------- bias screen
    def run_bias_screen(self, appraisal_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/appraisals/{appraisal_id}/run-bias-screen", payload, headers,
        )

    def list_bias_flags(self, appraisal_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/appraisals/{appraisal_id}/bias-flags", params, headers,
        )

    def adjudicate_bias_flag(self, flag_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/bias-flags/{flag_id}/adjudicate", payload, headers,
        )

    # -------------------------------------------------------- communications
    def create_communication(self, appraisal_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/appraisals/{appraisal_id}/communications", payload, headers,
        )

    def list_communications(self, appraisal_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/appraisals/{appraisal_id}/communications", params, headers,
        )

    # -------------------------------------------------------- value revisions
    def list_value_revisions(self, appraisal_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/appraisals/{appraisal_id}/value-revisions", params, headers,
        )

    # ----------------------------------------------------------- desk reviews
    def create_desk_review(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/desk-reviews", payload, headers)

    def get_desk_review(self, desk_review_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/desk-reviews/{desk_review_id}", None, headers)

    def list_desk_reviews(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/desk-reviews", params, headers)

    def submit_desk_review(self, desk_review_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/desk-reviews/{desk_review_id}/submit", payload, headers,
        )

    def decide_desk_review(self, desk_review_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/desk-reviews/{desk_review_id}/decide", payload, headers,
        )

    # ------------------------------------------------------ escalation orders
    def get_escalation_order(self, order_id: str, headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/escalation-orders/{order_id}", None, headers,
        )

    def list_escalation_orders(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/escalation-orders", params, headers)

    def assign_escalation_order(self, order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/escalation-orders/{order_id}/assign", payload, headers,
        )

    def complete_escalation_order(self, order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/escalation-orders/{order_id}/complete", payload, headers,
        )

    def cancel_escalation_order(self, order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/escalation-orders/{order_id}/cancel", payload, headers,
        )

    # ---------------------------------------------------------- ROV requests
    def create_rov_request(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/rov-requests", payload, headers)

    def get_rov_request(self, rov_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/rov-requests/{rov_id}", None, headers)

    def list_rov_requests(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/rov-requests", params, headers)

    def create_rov_evidence(self, rov_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rov-requests/{rov_id}/evidence", payload, headers,
        )

    def list_rov_evidence(self, rov_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/rov-requests/{rov_id}/evidence", params, headers,
        )

    def submit_rov_request(self, rov_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rov-requests/{rov_id}/submit", payload, headers,
        )

    def rov_appraiser_response(self, rov_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rov-requests/{rov_id}/appraiser-response", payload, headers,
        )

    def rov_next_round(self, rov_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rov-requests/{rov_id}/next-round", payload, headers,
        )

    def finalize_rov_request(self, rov_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/rov-requests/{rov_id}/finalize", payload, headers,
        )

    # ---------------------------------------------------------- dispute cases
    def create_dispute_case(self, payload, headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/dispute-cases", payload, headers)

    def get_dispute_case(self, dispute_id: str, headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispute-cases/{dispute_id}", None, headers)

    def list_dispute_cases(self, headers, params=None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/dispute-cases", params, headers)

    def dispute_amc_response(self, dispute_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispute-cases/{dispute_id}/amc-response", payload, headers,
        )

    def resolve_dispute_case(self, dispute_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/dispute-cases/{dispute_id}/resolve", payload, headers,
        )
