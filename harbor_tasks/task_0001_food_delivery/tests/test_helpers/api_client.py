"""API client: one method per endpoint defined by the food delivery platform PRD."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client. Every method returns the raw requests.Response."""

    # ──────────────── Restaurants ────────────────

    def create_restaurant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/restaurants", payload, headers)

    def list_restaurants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/restaurants", headers=headers, params=params)

    def get_restaurant(self, restaurant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/restaurants/{restaurant_id}", headers=headers)

    def patch_restaurant(self, restaurant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/api/restaurants/{restaurant_id}", payload, headers)

    def approve_restaurant(self, restaurant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/restaurants/{restaurant_id}/approve", headers=headers)

    def suspend_restaurant(self, restaurant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/restaurants/{restaurant_id}/suspend", headers=headers)

    def reinstate_restaurant(self, restaurant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/restaurants/{restaurant_id}/reinstate", headers=headers)

    def settle_restaurant(self, restaurant_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/restaurants/{restaurant_id}/settle", headers=headers)

    # ──────────────── Menu items ────────────────

    def create_menu_item(self, restaurant_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/restaurants/{restaurant_id}/menu-items", payload, headers
        )

    def patch_menu_item(self, menu_item_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/api/menu-items/{menu_item_id}", payload, headers)

    def list_menu_items(self, restaurant_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"/api/restaurants/{restaurant_id}/menu-items", headers=headers, params=params
        )

    # ──────────────── Riders ────────────────

    def create_rider(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/riders", payload, headers)

    def get_rider(self, rider_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/riders/{rider_id}", headers=headers)

    def rider_go_online(self, rider_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/riders/{rider_id}/go-online", headers=headers)

    def rider_go_offline(self, rider_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/riders/{rider_id}/go-offline", headers=headers)

    def suspend_rider(self, rider_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/riders/{rider_id}/suspend", headers=headers)

    # ──────────────── Customers ────────────────

    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # ──────────────── Orders ────────────────

    def create_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def accept_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/orders/{order_id}/accept", headers=headers)

    def cancel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/orders/{order_id}/cancel", headers=headers)

    def start_preparing_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/orders/{order_id}/start-preparing", headers=headers)

    def mark_order_ready(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/orders/{order_id}/ready", headers=headers)

    def dispatch_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/orders/{order_id}/dispatch", headers=headers)

    def create_return(self, order_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/orders/{order_id}/returns", payload, headers)

    # ──────────────── Assignments ────────────────

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/assignments/{assignment_id}/accept", headers=headers)

    def reject_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/assignments/{assignment_id}/reject", headers=headers)

    def pickup_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/assignments/{assignment_id}/pickup", headers=headers)

    def deliver_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/assignments/{assignment_id}/deliver", headers=headers)

    def cancel_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/assignments/{assignment_id}/cancel", headers=headers)

    # ──────────────── Returns ────────────────

    def get_return(self, return_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/returns/{return_id}", headers=headers)

    def approve_return(self, return_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/api/returns/{return_id}/approve", payload, headers)

    def reject_return(self, return_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/returns/{return_id}/reject", headers=headers)

    def escalate_return(self, return_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/returns/{return_id}/escalate", headers=headers)

    def reopen_return(self, return_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/returns/{return_id}/reopen", headers=headers)

    # ──────────────── Fines ────────────────

    def get_fine(self, fine_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/fines/{fine_id}", headers=headers)

    def list_fines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/api/fines", headers=headers, params=params)

    def waive_fine(self, fine_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/fines/{fine_id}/waive", headers=headers)

    # ──────────────── Work orders ────────────────

    def create_work_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/api/work-orders", payload, headers)

    def get_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/work-orders/{work_order_id}", headers=headers)

    def assign_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/work-orders/{work_order_id}/assign", headers=headers)

    def request_info_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/request-info", headers=headers
        )

    def submit_info_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/submit-info", headers=headers
        )

    def resolve_work_order(
        self, work_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/api/work-orders/{work_order_id}/resolve", payload, headers
        )

    def escalate_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/work-orders/{work_order_id}/escalate", headers=headers)

    def close_work_order(self, work_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/work-orders/{work_order_id}/close", headers=headers)

    # ──────────────── Clock (testability) ────────────────

    def advance_clock(self, seconds: int, headers: Dict[str, str]):
        return self._request("POST", "/api/_clock/advance", {"seconds": seconds}, headers)


api_client = ApiClient()
