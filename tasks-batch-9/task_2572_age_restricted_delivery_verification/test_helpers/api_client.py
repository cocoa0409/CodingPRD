"""One method per endpoint of PRD section 4.

Every method returns the raw ``requests.Response`` so tests can assert the
status code themselves. Listing methods accept ``params`` for the `limit` and
`offset` parameters of PRD 2.3 plus each listing's own filters.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Age-Restricted Delivery Verification API."""

    # ------------------------------------------------------------------
    # Logical clock (PRD 2.5)
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Jurisdictions (PRD 3.1)
    # ------------------------------------------------------------------
    def create_jurisdiction(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", None, headers)

    def list_jurisdictions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/jurisdictions", params, headers)

    # ------------------------------------------------------------------
    # Restriction policies (PRD 3.1)
    # ------------------------------------------------------------------
    def create_restriction_policy(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/restriction-policies", payload, headers)

    def get_restriction_policy(self, policy_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/restriction-policies/{policy_id}", None, headers)

    def list_jurisdiction_restriction_policies(
        self,
        jurisdiction_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/jurisdictions/{jurisdiction_id}/restriction-policies", params, headers
        )

    # ------------------------------------------------------------------
    # Products (PRD 3.1)
    # ------------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/products/{product_id}", None, headers)

    def list_products(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/products", params, headers)

    # ------------------------------------------------------------------
    # Customers, attestation and identity pre-verification (PRD 3.2)
    # ------------------------------------------------------------------
    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/customers/{customer_id}", None, headers)

    def list_customers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/customers", params, headers)

    def record_age_attestation(
        self, customer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/customers/{customer_id}/age-attestation", payload, headers
        )

    def create_identity_check(
        self, customer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/customers/{customer_id}/identity-checks", payload, headers
        )

    def list_identity_checks(
        self,
        customer_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/customers/{customer_id}/identity-checks", params, headers
        )

    # ------------------------------------------------------------------
    # Orders, lines and the order-time battery (PRD 3.3)
    # ------------------------------------------------------------------
    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/orders/{order_id}", None, headers)

    def list_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/orders", params, headers)

    def create_order_line(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, order_line_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/order-lines/{order_line_id}", None, headers)

    def list_order_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/order-lines", params, headers)

    def submit_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/submit", payload or {}, headers)

    def get_compliance_evaluation(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/orders/{order_id}/compliance-evaluation", None, headers)

    def record_clearance(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/clearance", payload, headers)

    def dispatch_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/dispatch", payload or {}, headers)

    def create_return_settlement(
        self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/return-settlement", payload, headers)

    # ------------------------------------------------------------------
    # Delivery partners (PRD 3.4)
    # ------------------------------------------------------------------
    def create_delivery_partner(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/delivery-partners", payload, headers)

    def get_delivery_partner(self, partner_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/delivery-partners/{partner_id}", None, headers)

    def list_delivery_partners(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/delivery-partners", params, headers)

    def get_risk_assessment(self, partner_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "GET", f"/delivery-partners/{partner_id}/risk-assessment", None, headers
        )

    # ------------------------------------------------------------------
    # Couriers and certifications (PRD 3.5)
    # ------------------------------------------------------------------
    def create_courier(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/couriers", payload, headers)

    def get_courier(self, courier_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/couriers/{courier_id}", None, headers)

    def list_couriers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/couriers", params, headers)

    def create_courier_certification(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/courier-certifications", payload, headers)

    def get_courier_certification(
        self, certification_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/courier-certifications/{certification_id}", None, headers
        )

    def list_courier_certifications(
        self,
        courier_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request("GET", f"/couriers/{courier_id}/certifications", params, headers)

    def renew_courier_certification(
        self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/courier-certifications/{certification_id}/renew", payload, headers
        )

    def revoke_courier_certification(
        self, certification_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/courier-certifications/{certification_id}/revoke", payload, headers
        )

    # ------------------------------------------------------------------
    # Delivery attempts, the door-side check and captures (PRD 3.6)
    # ------------------------------------------------------------------
    def create_delivery_attempt(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/delivery-attempts", payload, headers)

    def get_delivery_attempt(self, attempt_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/delivery-attempts/{attempt_id}", None, headers)

    def list_delivery_attempts(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/delivery-attempts", params, headers)

    def record_id_check(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-attempts/{attempt_id}/id-check", payload, headers
        )

    def record_handover(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-attempts/{attempt_id}/handover", payload, headers
        )

    def record_refusal(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-attempts/{attempt_id}/refuse", payload, headers
        )

    def create_capture(
        self, attempt_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/delivery-attempts/{attempt_id}/captures", payload, headers
        )

    def list_captures(
        self,
        attempt_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/delivery-attempts/{attempt_id}/captures", params, headers
        )

    # ------------------------------------------------------------------
    # Secret-shopper tests (PRD 3.8)
    # ------------------------------------------------------------------
    def create_secret_shopper_test(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/secret-shopper-tests", payload, headers)

    def get_secret_shopper_test(self, test_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/secret-shopper-tests/{test_id}", None, headers)

    def list_secret_shopper_tests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/secret-shopper-tests", params, headers)

    def record_shopper_outcome(
        self, test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/secret-shopper-tests/{test_id}/record-outcome", payload, headers
        )

    # ------------------------------------------------------------------
    # Violation cases (PRD 3.9)
    # ------------------------------------------------------------------
    def create_violation_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/violation-cases", payload, headers)

    def get_violation_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/violation-cases/{case_id}", None, headers)

    def list_violation_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/violation-cases", params, headers)

    def investigate_case(
        self,
        case_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/violation-cases/{case_id}/investigate", payload or {}, headers
        )

    def request_partner_response(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/violation-cases/{case_id}/request-partner-response", payload, headers
        )

    def record_partner_response(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/violation-cases/{case_id}/partner-response", payload, headers
        )

    def decide_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/violation-cases/{case_id}/decide", payload, headers)

    def reopen_case(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/violation-cases/{case_id}/reopen", payload, headers)

    # ------------------------------------------------------------------
    # Corrective action plans (PRD 3.9)
    # ------------------------------------------------------------------
    def create_corrective_action_plan(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/violation-cases/{case_id}/corrective-action-plans", payload, headers
        )

    def list_corrective_action_plans(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/violation-cases/{case_id}/corrective-action-plans", params, headers
        )

    def get_corrective_action_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/corrective-action-plans/{plan_id}", None, headers)

    def review_corrective_action_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-action-plans/{plan_id}/review", payload, headers
        )

    def resubmit_corrective_action_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-action-plans/{plan_id}/resubmit", payload, headers
        )

    def verify_corrective_action_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-action-plans/{plan_id}/verify", payload, headers
        )


# Module-level singleton the conftest `api` fixture hands to every test.
api_client = ApiClient()
