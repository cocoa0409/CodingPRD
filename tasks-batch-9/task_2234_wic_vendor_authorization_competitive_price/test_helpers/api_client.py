"""
HTTP client with one method per endpoint of the WIC vendor authorization API.

Conventions, uniform across the whole client:

* creates      -> ``create_x(payload, headers)``
* single reads -> ``get_x(x_id, headers)``
* list reads   -> ``list_x(headers, params=None)``
* actions      -> ``verb_x(x_id, payload, headers)`` with ``payload`` allowed to
  be ``None`` for the actions whose body is empty.

Every method returns the raw ``requests.Response`` so a test can assert the HTTP
status itself. All paths are absolute; the API is mounted at the server root with
no additional prefix.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint in the PRD endpoint table."""

    # ------------------------------------------------------------------
    # Peer groups
    # ------------------------------------------------------------------

    def create_peer_group(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/peer-groups", payload, headers)

    def get_peer_group(self, peer_group_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/peer-groups/{peer_group_id}", headers=headers)

    def list_peer_groups(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/peer-groups", headers=headers, params=params)

    def retire_peer_group(
        self,
        peer_group_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/peer-groups/{peer_group_id}/retire", payload, headers
        )

    # ------------------------------------------------------------------
    # Food categories
    # ------------------------------------------------------------------

    def create_food_category(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/food-categories", payload, headers)

    def get_food_category(self, food_category_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/food-categories/{food_category_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Authorized food items
    # ------------------------------------------------------------------

    def create_authorized_food_item(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/authorized-food-items", payload, headers)

    def get_authorized_food_item(self, food_item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/authorized-food-items/{food_item_id}", headers=headers
        )

    def list_authorized_food_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/authorized-food-items", headers=headers, params=params
        )

    def delist_authorized_food_item(
        self,
        food_item_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/authorized-food-items/{food_item_id}/delist", payload, headers
        )

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------

    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def get_vendor_risk_profile(
        self,
        vendor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET", f"/vendors/{vendor_id}/risk-profile", headers=headers, params=params
        )

    def record_training(
        self, vendor_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/vendors/{vendor_id}/record-training", payload, headers
        )

    def submit_application(
        self,
        vendor_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/vendors/{vendor_id}/submit-application", payload, headers
        )

    def authorize_vendor(
        self,
        vendor_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/vendors/{vendor_id}/authorize", payload, headers
        )

    def deny_vendor(
        self, vendor_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request("POST", f"/vendors/{vendor_id}/deny", payload, headers)

    def start_reauthorization(
        self,
        vendor_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/vendors/{vendor_id}/start-reauthorization", payload, headers
        )

    def complete_reauthorization(
        self,
        vendor_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/vendors/{vendor_id}/complete-reauthorization", payload, headers
        )

    # ------------------------------------------------------------------
    # Price cycles
    # ------------------------------------------------------------------

    def create_price_cycle(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/price-cycles", payload, headers)

    def get_price_cycle(self, price_cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/price-cycles/{price_cycle_id}", headers=headers)

    def close_price_cycle(
        self,
        price_cycle_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/price-cycles/{price_cycle_id}/close", payload, headers
        )

    def publish_ceilings(
        self,
        price_cycle_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/price-cycles/{price_cycle_id}/publish-ceilings", payload, headers
        )

    # ------------------------------------------------------------------
    # Price submissions
    # ------------------------------------------------------------------

    def create_price_submission(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/price-submissions", payload, headers)

    def get_price_submission(self, submission_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/price-submissions/{submission_id}", headers=headers
        )

    def list_price_submissions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/price-submissions", headers=headers, params=params
        )

    def review_price_submission(
        self,
        submission_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/price-submissions/{submission_id}/review", payload, headers
        )

    def revise_price_submission(
        self,
        submission_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST", f"/price-submissions/{submission_id}/revise", payload, headers
        )

    # ------------------------------------------------------------------
    # Price ceilings
    # ------------------------------------------------------------------

    def get_price_ceiling(self, price_ceiling_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/price-ceilings/{price_ceiling_id}", headers=headers
        )

    def list_price_ceilings(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/price-ceilings", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Monitoring visits
    # ------------------------------------------------------------------

    def create_monitoring_visit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/monitoring-visits", payload, headers)

    def get_monitoring_visit(self, visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/monitoring-visits/{visit_id}", headers=headers)

    def list_monitoring_visits(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/monitoring-visits", headers=headers, params=params
        )

    def record_observation(
        self, visit_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/monitoring-visits/{visit_id}/observations", payload, headers
        )

    def conduct_visit(
        self,
        visit_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/monitoring-visits/{visit_id}/conduct", payload, headers
        )

    # ------------------------------------------------------------------
    # Redemption claims
    # ------------------------------------------------------------------

    def create_redemption_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/redemption-claims", payload, headers)

    def get_redemption_claim(self, claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/redemption-claims/{claim_id}", headers=headers)

    def list_redemption_claims(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/redemption-claims", headers=headers, params=params
        )

    def adjudicate_claim(
        self,
        claim_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/redemption-claims/{claim_id}/adjudicate", payload, headers
        )

    def mark_claim_paid(
        self,
        claim_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/redemption-claims/{claim_id}/mark-paid", payload, headers
        )

    # ------------------------------------------------------------------
    # Claim lines
    # ------------------------------------------------------------------

    def get_claim_line(self, claim_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/claim-lines/{claim_line_id}", headers=headers)

    def list_claim_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/claim-lines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Reimbursement adjustments
    # ------------------------------------------------------------------

    def create_reimbursement_adjustment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/reimbursement-adjustments", payload, headers)

    def get_reimbursement_adjustment(self, adjustment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/reimbursement-adjustments/{adjustment_id}", headers=headers
        )

    def list_reimbursement_adjustments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/reimbursement-adjustments", headers=headers, params=params
        )

    def apply_adjustment(
        self,
        adjustment_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/reimbursement-adjustments/{adjustment_id}/apply", payload, headers
        )

    def reverse_adjustment(
        self,
        adjustment_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/reimbursement-adjustments/{adjustment_id}/reverse",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Sanction cases
    # ------------------------------------------------------------------

    def create_sanction_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sanction-cases", payload, headers)

    def get_sanction_case(self, sanction_case_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/sanction-cases/{sanction_case_id}", headers=headers
        )

    def list_sanction_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/sanction-cases", headers=headers, params=params)

    def serve_notice(
        self,
        sanction_case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/sanction-cases/{sanction_case_id}/serve-notice", payload, headers
        )

    def elect_cmp(
        self,
        sanction_case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/sanction-cases/{sanction_case_id}/elect-cmp", payload, headers
        )

    def impose_disqualification(
        self,
        sanction_case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST",
            f"/sanction-cases/{sanction_case_id}/impose-disqualification",
            payload,
            headers,
        )

    def dismiss_sanction_case(
        self,
        sanction_case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/sanction-cases/{sanction_case_id}/dismiss", payload, headers
        )

    def close_sanction_case(
        self,
        sanction_case_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request(
            "POST", f"/sanction-cases/{sanction_case_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Operational capabilities
    # ------------------------------------------------------------------

    def set_clock(
        self, current_utc: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        """Move the logical clock by supplying a ``current_utc`` instant."""
        from .test_users import SYSTEM_HEADERS

        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers if headers is not None else SYSTEM_HEADERS,
        )

    def risk_run(
        self,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Advance the risk epoch."""
        from .test_users import SYSTEM_HEADERS

        return self._request(
            "POST",
            "/_ops/risk-run",
            payload,
            headers if headers is not None else SYSTEM_HEADERS,
        )
