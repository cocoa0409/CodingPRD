"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Customers
    # =======================================================================
    def create_customer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str,
                     headers: Dict[str, str]):
        return self._request(
            "GET", f"/customers/{customer_id}", headers=headers,
        )

    def verify_customer_address(self, customer_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/customers/{customer_id}/shipping-address/verify",
            {}, headers,
        )

    # =======================================================================
    # Pets
    # =======================================================================
    def create_pet(self, customer_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/pets",
            payload, headers,
        )

    def list_pets(self, customer_id: str, headers: Dict[str, str],
                  params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/customers/{customer_id}/pets",
            headers=headers, params=params,
        )

    def get_pet(self, customer_id: str, pet_id: str,
                headers: Dict[str, str]):
        return self._request(
            "GET", f"/customers/{customer_id}/pets/{pet_id}",
            headers=headers,
        )

    def update_pet(self, customer_id: str, pet_id: str,
                   payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/customers/{customer_id}/pets/{pet_id}",
            payload, headers,
        )

    def add_pet_photo(self, customer_id: str, pet_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/pets/{pet_id}/photos",
            payload, headers,
        )

    # =======================================================================
    # Subscriptions
    # =======================================================================
    def create_subscription(self, customer_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/subscriptions",
            payload, headers,
        )

    def get_subscription(self, sub_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/subscriptions/{sub_id}", headers=headers,
        )

    def update_subscription(self, sub_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/subscriptions/{sub_id}",
            payload, headers,
        )

    def verify_subscription_address(self, sub_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/subscriptions/{sub_id}/shipping-address/verify",
            {}, headers,
        )

    def activate_subscription(self, sub_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/activate",
            {}, headers,
        )

    def pause_subscription(self, sub_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/pause",
            payload, headers,
        )

    def resume_subscription(self, sub_id: str,
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/resume",
            {}, headers,
        )

    def cancel_subscription(self, sub_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/cancel",
            payload, headers,
        )

    def reactivate_subscription(self, sub_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/subscriptions/{sub_id}/reactivate",
            {}, headers,
        )

    # =======================================================================
    # Orders
    # =======================================================================
    def list_orders(self, sub_id: str, headers: Dict[str, str],
                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/subscriptions/{sub_id}/orders",
            headers=headers, params=params,
        )

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/orders/{order_id}", headers=headers,
        )

    def confirm_order(self, order_id: str,
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/confirm", {}, headers,
        )

    def skip_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/skip", {}, headers,
        )

    def submit_feedback(self, order_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/feedback",
            payload, headers,
        )

    def post_payment_event(self, order_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/events/payment",
            payload, headers,
        )

    def post_logistics_event(self, order_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/orders/{order_id}/events/logistics",
            payload, headers,
        )

    # =======================================================================
    # Recipe adjustments (under a Pet)
    # =======================================================================
    def list_recipe_adjustments(self, pet_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/pets/{pet_id}/recipe-adjustments",
            headers=headers, params=params,
        )

    def get_recipe_adjustment(self, pet_id: str, adj_id: str,
                              headers: Dict[str, str]):
        return self._request(
            "GET", f"/pets/{pet_id}/recipe-adjustments/{adj_id}",
            headers=headers,
        )

    def apply_recipe_adjustment(self, pet_id: str, adj_id: str,
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pets/{pet_id}/recipe-adjustments/{adj_id}/apply",
            {}, headers,
        )

    def dismiss_recipe_adjustment(self, pet_id: str, adj_id: str,
                                  headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pets/{pet_id}/recipe-adjustments/{adj_id}/dismiss",
            {}, headers,
        )

    def escalate_recipe_adjustment(self, pet_id: str, adj_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pets/{pet_id}/recipe-adjustments/{adj_id}/escalate",
            {}, headers,
        )

    def post_vet_event(self, pet_id: str, adj_id: str,
                       payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/pets/{pet_id}/recipe-adjustments/{adj_id}/events/vet",
            payload, headers,
        )

    # =======================================================================
    # Recipe catalog
    # =======================================================================
    def create_recipe(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/recipes", payload, headers)

    def list_recipes(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/recipes", headers=headers, params=params,
        )

    def get_recipe(self, recipe_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/recipes/{recipe_id}", headers=headers,
        )

    def list_recipe_recommendations(self, pet_id: str,
                                    headers: Dict[str, str],
                                    params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/pets/{pet_id}/recipe-recommendations",
            headers=headers, params=params,
        )

    # =======================================================================
    # Warehouses + Inventory
    # =======================================================================
    def create_warehouse(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/warehouses", payload, headers)

    def list_warehouses(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/warehouses", headers=headers, params=params,
        )

    def update_warehouse(self, warehouse_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/warehouses/{warehouse_id}",
            payload, headers,
        )

    def create_inventory_lot(self, warehouse_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/warehouses/{warehouse_id}/inventory-lots",
            payload, headers,
        )

    def list_inventory_lots(self, warehouse_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/warehouses/{warehouse_id}/inventory-lots",
            headers=headers, params=params,
        )

    # =======================================================================
    # Audit log
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driver endpoints (PRD §3.7)
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "POST", "/_events/emit", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
