"""API client: one method per endpoint defined in the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/dropship"


class ApiClient(GenericApiClient):
    """Typed access to all 44 endpoints of the dropship vendor program."""

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers=headers,
        )

    def set_clock_raw(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers=headers
        )

    # ─── Vendors ──────────────────────────────────────

    def create_vendor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/vendors", payload, headers=headers)

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/vendors/{vendor_id}", headers=headers)

    def begin_integration(self, vendor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/begin-integration", {}, headers=headers
        )

    def record_integration_test(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/vendors/{vendor_id}/integration-tests",
            payload,
            headers=headers,
        )

    def list_integration_tests(
        self,
        vendor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/vendors/{vendor_id}/integration-tests",
            headers=headers,
            params=params,
        )

    def evaluate_integration_test(
        self, test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/integration-tests/{test_id}/evaluate",
            payload,
            headers=headers,
        )

    def certify_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/certify", {}, headers=headers
        )

    def activate_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/activate", {}, headers=headers
        )

    def suspend_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/suspend", {}, headers=headers
        )

    def reinstate_vendor(self, vendor_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/reinstate", {}, headers=headers
        )

    # ─── Serviceability coverage ──────────────────────

    def create_serviceability_rule(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/vendors/{vendor_id}/serviceability-rules",
            payload,
            headers=headers,
        )

    def list_serviceability_rules(
        self,
        vendor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/vendors/{vendor_id}/serviceability-rules",
            headers=headers,
            params=params,
        )

    # ─── Blackouts ────────────────────────────────────

    def create_blackout(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/blackouts", payload, headers=headers
        )

    def list_blackouts(
        self,
        vendor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/vendors/{vendor_id}/blackouts",
            headers=headers,
            params=params,
        )

    def cancel_blackout(
        self, vendor_id: str, blackout_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "DELETE",
            f"{PREFIX}/vendors/{vendor_id}/blackouts/{blackout_id}",
            headers=headers,
        )

    # ─── Offers (dropship items) ──────────────────────

    def create_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/items", payload, headers=headers)

    def get_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/items/{item_id}", headers=headers)

    def list_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/items", headers=headers, params=params)

    def update_item(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{PREFIX}/items/{item_id}", payload, headers=headers
        )

    def activate_item(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/items/{item_id}/activate", {}, headers=headers
        )

    def suppress_item(self, item_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/items/{item_id}/suppress", {}, headers=headers
        )

    # ─── Inventory feed ───────────────────────────────

    def create_inventory_snapshot(
        self, item_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/items/{item_id}/inventory-snapshots",
            payload,
            headers=headers,
        )

    def list_inventory_snapshots(
        self,
        item_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/items/{item_id}/inventory-snapshots",
            headers=headers,
            params=params,
        )

    # ─── Orders ───────────────────────────────────────

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/orders", payload, headers=headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def get_order_promise(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/promise", headers=headers
        )

    def transmit_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/transmit", {}, headers=headers
        )

    # ─── Order lines ──────────────────────────────────

    def get_order_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/order-lines/{line_id}", headers=headers)

    def list_order_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", f"{PREFIX}/order-lines", headers=headers, params=params
        )

    def acknowledge_line(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/order-lines/{line_id}/acknowledge",
            payload,
            headers=headers,
        )

    def ship_confirm_line(
        self, line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/order-lines/{line_id}/ship-confirm",
            payload,
            headers=headers,
        )

    def cancel_line(self, line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/order-lines/{line_id}/cancel", {}, headers=headers
        )

    def retransmit_line(self, line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/order-lines/{line_id}/retransmit", {}, headers=headers
        )

    def list_shipment_confirmations(
        self,
        line_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/order-lines/{line_id}/shipment-confirmations",
            headers=headers,
            params=params,
        )

    # ─── Returns ──────────────────────────────────────

    def create_return(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/returns", payload, headers=headers)

    def get_return(self, return_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{PREFIX}/returns/{return_id}", headers=headers)

    def list_returns(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", f"{PREFIX}/returns", headers=headers, params=params)

    def authorize_return(self, return_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/returns/{return_id}/authorize", {}, headers=headers
        )

    def receive_return(
        self,
        return_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"{PREFIX}/returns/{return_id}/receive",
            payload if payload is not None else {},
            headers=headers,
        )

    def reject_return(
        self, return_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/returns/{return_id}/reject", payload, headers=headers
        )

    # ─── Scorecards ───────────────────────────────────

    def create_scorecard(
        self, vendor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{PREFIX}/vendors/{vendor_id}/scorecards", payload, headers=headers
        )

    def list_scorecards(
        self,
        vendor_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "GET",
            f"{PREFIX}/vendors/{vendor_id}/scorecards",
            headers=headers,
            params=params,
        )

    def publish_scorecard(
        self, scorecard_id: str, expected_vendor_version: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/scorecards/{scorecard_id}/publish",
            {"expected_vendor_version": expected_vendor_version},
            headers=headers,
        )

    def publish_scorecard_raw(
        self, scorecard_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{PREFIX}/scorecards/{scorecard_id}/publish",
            payload,
            headers=headers,
        )


api_client = ApiClient()
