"""ApiClient: one method per endpoint declared in PRD 4.

Every method returns the raw `requests.Response` so tests can assert both the
HTTP status and the envelope. Bodies are passed through untouched, which lets
tests send deliberately malformed payloads.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        """POST /_clock/set_current_utc"""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -------------------------------------------------------- state policies
    def create_state_policy(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/state-policies", payload, headers)

    def get_state_policy(self, policy_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/state-policies/{policy_id}", None, headers)

    def list_state_policies(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/state-policies", params, headers)

    # ----------------------------------------------------------------- cooks
    def create_cook(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/cooks", payload, headers)

    def get_cook(self, cook_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/cooks/{cook_id}", None, headers)

    def list_cooks(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/cooks", params, headers)

    def get_compliance_summary(self, cook_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/cooks/{cook_id}/compliance-summary", None, headers)

    def cook_onboarding_decision(
        self, cook_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cooks/{cook_id}/onboarding-decision", payload, headers)

    def cook_standing_action(
        self, cook_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cooks/{cook_id}/standing-actions", payload, headers)

    # ------------------------------------------------- onboarding documents
    def create_onboarding_document(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/onboarding-documents", payload, headers)

    def review_onboarding_document(
        self, document_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/onboarding-documents/{document_id}/review", payload, headers
        )

    def get_onboarding_document(
        self, document_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/onboarding-documents/{document_id}", None, headers)

    def list_onboarding_documents(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/onboarding-documents", params, headers)

    # ------------------------------------------------------------ menu items
    def create_menu_item(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/menu-items", payload, headers)

    def submit_menu_item(
        self, menu_item_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/menu-items/{menu_item_id}/submit", payload if payload is not None else {}, headers
        )

    def review_menu_item(
        self, menu_item_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/menu-items/{menu_item_id}/review", payload, headers)

    def get_menu_item(self, menu_item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/menu-items/{menu_item_id}", None, headers)

    def list_menu_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/menu-items", params, headers)

    # ----------------------------------------------------- production windows
    def create_production_window(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/production-windows", payload, headers)

    def advance_production_window(
        self, window_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/production-windows/{window_id}/advance", payload, headers)

    def get_production_window(self, window_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/production-windows/{window_id}", None, headers)

    def list_production_windows(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/production-windows", params, headers)

    # --------------------------------------------------------- delivery zones
    def create_delivery_zone(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/delivery-zones", payload, headers)

    def get_delivery_zone(self, zone_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/delivery-zones/{zone_id}", None, headers)

    def list_delivery_zones(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/delivery-zones", params, headers)

    # ------------------------------------------------------------ pickup hubs
    def create_pickup_hub(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/pickup-hubs", payload, headers)

    def consolidate_pickup_hub(
        self, hub_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/pickup-hubs/{hub_id}/consolidate", payload, headers)

    def get_pickup_hub(self, hub_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/pickup-hubs/{hub_id}", None, headers)

    def list_pickup_hubs(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/pickup-hubs", params, headers)

    # ----------------------------------------------------------------- orders
    def create_order(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/orders", payload, headers)

    def route_order(
        self, order_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/orders/{order_id}/route", payload if payload is not None else {}, headers
        )

    def advance_order(
        self, order_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/advance", payload, headers)

    def cancel_order(
        self, order_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/orders/{order_id}/cancel", payload if payload is not None else {}, headers
        )

    def get_order(self, order_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/orders/{order_id}", None, headers)

    def list_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/orders", params, headers)

    # -------------------------------------------------------- safety incidents
    def create_safety_incident(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/safety-incidents", payload, headers)

    def triage_safety_incident(
        self, incident_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/safety-incidents/{incident_id}/triage", payload, headers)

    def adjudicate_safety_incident(
        self, incident_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/safety-incidents/{incident_id}/adjudicate", payload, headers
        )

    def get_safety_incident(self, incident_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/safety-incidents/{incident_id}", None, headers)

    def list_safety_incidents(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/safety-incidents", params, headers)

    # -------------------------------------------------------- payout statements
    def create_payout_statement(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/payout-statements", payload, headers)

    def advance_payout_statement(
        self, statement_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/payout-statements/{statement_id}/advance", payload, headers
        )

    def get_payout_statement(self, statement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/payout-statements/{statement_id}", None, headers)

    def list_payout_statements(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/payout-statements", params, headers)

    # ----------------------------------------------------------- refund events
    def create_refund_event(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/refund-events", payload, headers)

    def get_refund_event(self, refund_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/refund-events/{refund_id}", None, headers)

    def list_refund_events(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/refund-events", params, headers)


api_client = ApiClient()
