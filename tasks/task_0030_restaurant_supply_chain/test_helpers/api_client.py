"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response. Tests pass headers explicitly because PRD §2.1 makes
X-User-ID / X-User-Role mandatory for every call.

PRD §1: 'The API is mounted under /supply-chain.' All paths therefore
include the /supply-chain prefix.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


PREFIX = "/supply-chain"


class ApiClient(GenericApiClient):
    # =====================================================================
    # Stores
    # =====================================================================
    def create_store(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def list_stores(self, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/stores", headers=headers, params=params
        )

    def get_store(self, store_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/stores/{store_id}", headers=headers
        )

    def patch_store(self, store_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"{PREFIX}/stores/{store_id}", payload, headers
        )

    # =====================================================================
    # Recipes & ingredients
    # =====================================================================
    def create_recipe(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/recipes", payload, headers)

    def list_recipes(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/recipes", headers=headers, params=params
        )

    def get_recipe(self, recipe_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/recipes/{recipe_id}", headers=headers
        )

    def create_ingredient(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/ingredients", payload, headers
        )

    def attach_recipe_ingredient(self, recipe_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/recipes/{recipe_id}/ingredients",
            payload,
            headers,
        )

    # =====================================================================
    # Store orders
    # =====================================================================
    def create_store_order(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/store-orders", payload, headers
        )

    def append_order_line(self, order_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/store-orders/{order_id}/lines",
            payload,
            headers,
        )

    def submit_store_order(self, order_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/store-orders/{order_id}/submit",
            payload or {},
            headers,
        )

    def cancel_store_order(self, order_id: str, headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/store-orders/{order_id}/cancel",
            payload or {},
            headers,
        )

    def patch_store_order(self, order_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "PATCH",
            f"{PREFIX}/store-orders/{order_id}",
            payload,
            headers,
        )

    def list_store_orders(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/store-orders", headers=headers, params=params
        )

    def get_store_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/store-orders/{order_id}", headers=headers
        )

    # =====================================================================
    # Production batches
    # =====================================================================
    def consolidate_production_batches(self, payload: Dict[str, Any],
                                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/consolidate",
            payload,
            headers,
        )

    def list_production_batches(self, headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"{PREFIX}/production-batches",
            headers=headers,
            params=params,
        )

    def get_production_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{PREFIX}/production-batches/{batch_id}", headers=headers
        )

    def get_production_batch_forecast(self, batch_id: str,
                                      headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{PREFIX}/production-batches/{batch_id}/forecast",
            headers=headers,
        )

    def schedule_production_batch(self, batch_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/{batch_id}/schedule",
            payload or {},
            headers,
        )

    def start_production_batch(self, batch_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/{batch_id}/start",
            payload or {},
            headers,
        )

    def complete_production_batch(self, batch_id: str,
                                  headers: Dict[str, str],
                                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/{batch_id}/complete",
            payload or {},
            headers,
        )

    def fail_production_batch(self, batch_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/production-batches/{batch_id}/fail",
            payload or {},
            headers,
        )

    # =====================================================================
    # Vehicles & delivery routes
    # =====================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", f"{PREFIX}/vehicles", payload, headers)

    def list_vehicles(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/vehicles", headers=headers, params=params
        )

    def create_delivery_route(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/delivery-routes", payload, headers
        )

    def list_delivery_routes(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"{PREFIX}/delivery-routes",
            headers=headers,
            params=params,
        )

    def dispatch_route(self, route_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/delivery-routes/{route_id}/dispatch",
            payload or {},
            headers,
        )

    def depart_route(self, route_id: str, headers: Dict[str, str],
                     payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/delivery-routes/{route_id}/depart",
            payload or {},
            headers,
        )

    def complete_route(self, route_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/delivery-routes/{route_id}/complete",
            payload or {},
            headers,
        )

    def raise_exception(self, route_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/delivery-routes/{route_id}/raise-exception",
            payload,
            headers,
        )

    def reroute_route(self, route_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/delivery-routes/{route_id}/reroute",
            payload,
            headers,
        )

    # =====================================================================
    # Inventory batches
    # =====================================================================
    def list_inventory_batches(self, headers: Dict[str, str],
                               params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"{PREFIX}/inventory-batches",
            headers=headers,
            params=params,
        )

    def adjust_inventory_batch(self, batch_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/inventory-batches/{batch_id}/adjust",
            payload,
            headers,
        )

    def transfer_inventory_batch(self, batch_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/inventory-batches/{batch_id}/transfer",
            payload,
            headers,
        )

    def dispose_inventory_batch(self, batch_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/inventory-batches/{batch_id}/dispose",
            payload or {},
            headers,
        )

    # =====================================================================
    # Replenishment rules
    # =====================================================================
    def create_replenishment_rule(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/replenishment-rules", payload, headers
        )

    def list_replenishment_rules(self, headers: Dict[str, str],
                                 params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"{PREFIX}/replenishment-rules",
            headers=headers,
            params=params,
        )

    def suspend_replenishment_rule(self, rule_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/replenishment-rules/{rule_id}/suspend",
            payload or {},
            headers,
        )

    def activate_replenishment_rule(self, rule_id: str,
                                    headers: Dict[str, str],
                                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/replenishment-rules/{rule_id}/activate",
            payload or {},
            headers,
        )

    def manual_replenish(self, rule_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/replenishment-rules/{rule_id}/manual-replenish",
            payload or {},
            headers,
        )

    # =====================================================================
    # Loss records
    # =====================================================================
    def create_loss_record(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/loss-records", payload, headers
        )

    def list_loss_records(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"{PREFIX}/loss-records",
            headers=headers,
            params=params,
        )

    def approve_loss_record(self, record_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/loss-records/{record_id}/approve",
            payload or {},
            headers,
        )

    def reverse_loss_record(self, record_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/loss-records/{record_id}/reverse",
            payload or {},
            headers,
        )

    def resolve_investigation(self, record_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"{PREFIX}/loss-records/{record_id}/resolve-investigation",
            payload or {},
            headers,
        )

    # =====================================================================
    # Cost allocation & audit
    # =====================================================================
    def run_cost_allocation(self, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/cost-allocations/run", payload, headers
        )

    def list_audit_log(self, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"{PREFIX}/audit-log", headers=headers, params=params
        )

    # =====================================================================
    # Test-driving capabilities (PRD §2.11)
    # =====================================================================
    def advance_clock(self, to_iso: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/advance",
            {"to_iso8601": to_iso},
            headers,
        )

    def run_expiry_sweep(self, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_sweep/expiry-alerts", {}, headers
        )

    def run_replenish_sweep(self, headers: Dict[str, str]):
        return self._request(
            "POST", f"{PREFIX}/_sweep/replenish", {}, headers
        )

    def emit_event(self, system: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{PREFIX}/_events/emit",
            {"system": system, "payload": payload},
            headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client", "PREFIX"]
