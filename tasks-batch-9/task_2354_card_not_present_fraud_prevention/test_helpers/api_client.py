"""Typed client covering every endpoint of the Aegis CNP fraud-prevention API.

Every method accepts an explicit ``headers`` mapping so that each call declares
the role and the acting principal it is made under. For the two entity-backed
roles the caller must pass the ``id`` of the acting ``Analyst`` row.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per documented operation."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    def create_customer(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/customers", payload, headers)

    def list_customers(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/customers", None, headers, params)

    def get_customer(self, customer_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/customers/{customer_id}", None, headers)

    def set_customer_posture(
        self, customer_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/customers/{customer_id}/posture", payload, headers
        )

    # ------------------------------------------------------------------
    # Analysts
    # ------------------------------------------------------------------

    def create_analyst(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/analysts", payload, headers)

    def list_analysts(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/analysts", None, headers, params)

    def get_analyst(self, analyst_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/analysts/{analyst_id}", None, headers)

    def set_analyst_shift(
        self, analyst_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/analysts/{analyst_id}/shift", payload, headers
        )

    # ------------------------------------------------------------------
    # Device profiles
    # ------------------------------------------------------------------

    def create_device(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/devices", payload, headers)

    def list_devices(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", "/fraud/devices", None, headers, params)

    def get_device(self, device_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/devices/{device_id}", None, headers)

    # ------------------------------------------------------------------
    # Addresses
    # ------------------------------------------------------------------

    def create_address(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/addresses", payload, headers)

    def list_addresses(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/addresses", None, headers, params)

    def get_address(self, address_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/addresses/{address_id}", None, headers)

    # ------------------------------------------------------------------
    # Rule packs and fraud rules
    # ------------------------------------------------------------------

    def create_rule_pack(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/rule-packs", payload, headers)

    def list_rule_packs(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/rule-packs", None, headers, params)

    def get_rule_pack(self, pack_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/rule-packs/{pack_id}", None, headers)

    def activate_rule_pack(self, pack_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/fraud/rule-packs/{pack_id}/activate", None, headers
        )

    def get_rule_pack_performance(
        self, pack_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/fraud/rule-packs/{pack_id}/performance", None, headers, params
        )

    def create_rule(
        self, pack_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/rule-packs/{pack_id}/rules", payload, headers
        )

    def list_rules(
        self, pack_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/fraud/rule-packs/{pack_id}/rules", None, headers, params
        )

    def get_rule(self, rule_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/rules/{rule_id}", None, headers)

    # ------------------------------------------------------------------
    # Risk models
    # ------------------------------------------------------------------

    def create_risk_model(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/risk-models", payload, headers)

    def list_risk_models(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/risk-models", None, headers, params)

    def get_risk_model(self, model_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/risk-models/{model_id}", None, headers)

    def risk_model_lifecycle(
        self, model_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/risk-models/{model_id}/lifecycle", payload, headers
        )

    # ------------------------------------------------------------------
    # Checkout assessments
    # ------------------------------------------------------------------

    def create_assessment(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/checkout-assessments", payload, headers)

    def list_assessments(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/checkout-assessments", None, headers, params)

    def get_assessment(self, assessment_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/fraud/checkout-assessments/{assessment_id}", None, headers
        )

    def score_assessment(
        self, assessment_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/checkout-assessments/{assessment_id}/score", None, headers
        )

    # ------------------------------------------------------------------
    # Review cases
    # ------------------------------------------------------------------

    def list_review_cases(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/review-cases", None, headers, params)

    def get_review_case(self, case_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/review-cases/{case_id}", None, headers)

    def assign_case(
        self, case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/review-cases/{case_id}/assign", payload, headers
        )

    def auto_assign_case(self, case_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST", f"/fraud/review-cases/{case_id}/auto-assign", None, headers
        )

    def resolve_case(
        self, case_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/review-cases/{case_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------
    # Authentication events and step-up challenges
    # ------------------------------------------------------------------

    def create_auth_event(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/auth-events", payload, headers)

    def list_auth_events(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/auth-events", None, headers, params)

    def get_auth_event(self, event_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/auth-events/{event_id}", None, headers)

    def challenge(
        self, event_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/auth-events/{event_id}/challenge", payload, headers
        )

    # ------------------------------------------------------------------
    # Chargebacks
    # ------------------------------------------------------------------

    def create_chargeback(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", "/fraud/chargebacks", payload, headers)

    def list_chargebacks(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/chargebacks", None, headers, params)

    def get_chargeback(self, chargeback_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/fraud/chargebacks/{chargeback_id}", None, headers)

    def transition_chargeback(
        self, chargeback_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/fraud/chargebacks/{chargeback_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Policy exceptions
    # ------------------------------------------------------------------

    def create_policy_exception(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/fraud/policy-exceptions", payload, headers)

    def list_policy_exceptions(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/fraud/policy-exceptions", None, headers, params)

    def get_policy_exception(
        self, exception_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/fraud/policy-exceptions/{exception_id}", None, headers
        )

    def decide_policy_exception(
        self, exception_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/fraud/policy-exceptions/{exception_id}/decision",
            payload,
            headers,
        )


#: Module-level singleton shared by the whole suite.
api_client = ApiClient()
