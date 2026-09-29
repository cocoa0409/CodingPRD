"""One method per endpoint in the API surface.

Every method returns the raw ``requests.Response`` so tests can assert on the
HTTP status code as well as the payload.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]
Params = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Typed client for the made-to-order foodservice API."""

    # ─── Stores ───────────────────────────────────────────────────────
    def create_store(self, payload: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/stores", payload or {}, headers)

    def get_store(self, store_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}", None, headers)

    def get_store_readiness(self, store_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}/readiness", None, headers)

    def create_daypart_transition(
        self, store_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/stores/{store_id}/daypart-transitions", payload or {}, headers
        )

    # ─── Holding units ────────────────────────────────────────────────
    def create_holding_unit(
        self, store_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/stores/{store_id}/holding-units", payload or {}, headers)

    def list_store_holding_units(
        self, store_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}/holding-units", params, headers)

    def get_holding_unit(self, unit_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/holding-units/{unit_id}", None, headers)

    # ─── Menu items and modifier options ──────────────────────────────
    def create_menu_item(self, payload: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/menu-items", payload or {}, headers)

    def get_menu_item(self, item_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/menu-items/{item_id}", None, headers)

    def create_modifier_option(
        self, item_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/menu-items/{item_id}/modifier-options", payload or {}, headers)

    def list_modifier_options(
        self, item_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/menu-items/{item_id}/modifier-options", params, headers)

    # ─── Promotion rules ──────────────────────────────────────────────
    def create_promotion_rule(
        self, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/promotion-rules", payload or {}, headers)

    def suspend_promotion_rule(
        self, rule_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/promotion-rules/{rule_id}/suspend", payload or {}, headers)

    def list_promotion_rules(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/promotion-rules", params, headers)

    # ─── Loyalty ──────────────────────────────────────────────────────
    def create_loyalty_account(
        self, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/loyalty-accounts", payload or {}, headers)

    def get_loyalty_account(self, account_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/loyalty-accounts/{account_id}", None, headers)

    def create_points_adjustment(
        self, account_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loyalty-accounts/{account_id}/points-adjustments", payload or {}, headers
        )

    def create_fuel_transaction(
        self, account_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/loyalty-accounts/{account_id}/fuel-transactions", payload or {}, headers
        )

    def list_fuel_transactions(
        self, account_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/loyalty-accounts/{account_id}/fuel-transactions", params, headers
        )

    # ─── Staffing plans ───────────────────────────────────────────────
    def create_staffing_plan(
        self, store_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/stores/{store_id}/staffing-plans", payload or {}, headers)

    def list_staffing_plans(
        self, store_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}/staffing-plans", params, headers)

    def publish_staffing_plan(
        self, plan_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/staffing-plans/{plan_id}/publish", payload or {}, headers)

    def lock_staffing_plan(
        self, plan_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/staffing-plans/{plan_id}/lock", payload or {}, headers)

    # ─── Production batches ───────────────────────────────────────────
    def create_production_batch(
        self, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/production-batches", payload or {}, headers)

    def get_production_batch(self, batch_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/production-batches/{batch_id}", None, headers)

    def list_production_batches(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/production-batches", params, headers)

    def bake_production_batch(
        self, batch_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/production-batches/{batch_id}/bake", payload or {}, headers)

    def pull_production_batch(
        self, batch_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/production-batches/{batch_id}/pull", payload or {}, headers)

    def discard_production_batch(
        self, batch_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/production-batches/{batch_id}/discard", payload or {}, headers
        )

    def list_batch_waste_logs(
        self, batch_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/production-batches/{batch_id}/waste-logs", params, headers)

    # ─── Food safety ──────────────────────────────────────────────────
    def create_temperature_log(
        self, unit_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/holding-units/{unit_id}/temperature-logs", payload or {}, headers
        )

    def list_temperature_logs(
        self, unit_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/holding-units/{unit_id}/temperature-logs", params, headers)

    def create_corrective_action(
        self, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/corrective-actions", payload or {}, headers)

    def verify_corrective_action(
        self, action_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/corrective-actions/{action_id}/verify", payload or {}, headers)

    def list_corrective_actions(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/corrective-actions", params, headers)

    def get_corrective_action(self, action_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/corrective-actions/{action_id}", None, headers)

    # ─── Orders ───────────────────────────────────────────────────────
    def create_order(self, payload: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/orders", payload or {}, headers)

    def get_order(self, order_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/orders/{order_id}", None, headers)

    def list_orders(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", "/orders", params, headers)

    def create_order_line(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/lines", payload or {}, headers)

    def delete_order_line(
        self, order_id: str, line_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("DELETE", f"/orders/{order_id}/lines/{line_id}", None, headers)

    def get_order_line(self, line_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/order-lines/{line_id}", None, headers)

    def list_order_lines(self, headers: Headers = None, params: Params = None) -> requests.Response:
        return self._request("GET", "/order-lines", params, headers)

    def place_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/place", payload or {}, headers)

    def authorize_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/authorize", payload or {}, headers)

    def settle_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/settle", payload or {}, headers)

    def refund_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/refund", payload or {}, headers)

    def release_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/release", payload or {}, headers)

    def void_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/void", payload or {}, headers)

    def pickup_order(
        self, order_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/pickup", payload or {}, headers)

    # ─── Kitchen tickets ──────────────────────────────────────────────
    def list_order_kitchen_tickets(
        self, order_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/orders/{order_id}/kitchen-tickets", params, headers)

    def get_store_kitchen_queue(
        self, store_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"/stores/{store_id}/kitchen-queue", params, headers)

    def get_kitchen_ticket(self, ticket_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"/kitchen-tickets/{ticket_id}", None, headers)

    def list_kitchen_tickets(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/kitchen-tickets", params, headers)

    def start_kitchen_ticket(
        self, ticket_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/kitchen-tickets/{ticket_id}/start", payload or {}, headers)

    def complete_kitchen_ticket(
        self, ticket_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/kitchen-tickets/{ticket_id}/complete", payload or {}, headers)

    def reopen_kitchen_ticket(
        self, ticket_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", f"/kitchen-tickets/{ticket_id}/reopen", payload or {}, headers)

    # ─── Logical clock ────────────────────────────────────────────────
    def set_clock(self, payload: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload or {}, headers)


api_client = ApiClient()
