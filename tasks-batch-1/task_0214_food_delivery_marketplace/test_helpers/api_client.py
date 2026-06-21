"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() does the
envelope handling, header injection, and HTTP transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -----------------------------------------------------------------
    # Zone
    # -----------------------------------------------------------------
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    # -----------------------------------------------------------------
    # Restaurant
    # -----------------------------------------------------------------
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/restaurants", payload, headers=headers)

    def list_restaurants(self, headers, params=None):
        return self._request("GET", "/restaurants", headers=headers, params=params)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/restaurants/{restaurant_id}", headers=headers)

    def update_restaurant(self, restaurant_id, payload, headers):
        return self._request("PATCH", f"/restaurants/{restaurant_id}", payload, headers=headers)

    def deactivate_restaurant(self, restaurant_id, headers):
        return self._request("POST", f"/restaurants/{restaurant_id}/deactivate", {}, headers=headers)

    def create_menu_item(self, restaurant_id, payload, headers):
        return self._request("POST", f"/restaurants/{restaurant_id}/menu-items", payload, headers=headers)

    def list_menu_items(self, restaurant_id, headers, params=None):
        return self._request("GET", f"/restaurants/{restaurant_id}/menu-items", headers=headers, params=params)

    # -----------------------------------------------------------------
    # MenuItem
    # -----------------------------------------------------------------
    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def list_menu_item_line_items(self, menu_item_id, headers, params=None):
        return self._request("GET", f"/menu-items/{menu_item_id}/line-items", headers=headers, params=params)

    def update_menu_item(self, menu_item_id, payload, headers):
        return self._request("PATCH", f"/menu-items/{menu_item_id}", payload, headers=headers)

    def delist_menu_item(self, menu_item_id, headers):
        return self._request("POST", f"/menu-items/{menu_item_id}/delist", {}, headers=headers)

    # -----------------------------------------------------------------
    # Customer
    # -----------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # -----------------------------------------------------------------
    # Dasher
    # -----------------------------------------------------------------
    def create_dasher(self, payload, headers):
        return self._request("POST", "/dashers", payload, headers=headers)

    def list_dashers(self, headers, params=None):
        return self._request("GET", "/dashers", headers=headers, params=params)

    def get_dasher(self, dasher_id, headers):
        return self._request("GET", f"/dashers/{dasher_id}", headers=headers)

    def update_dasher(self, dasher_id, payload, headers):
        return self._request("PATCH", f"/dashers/{dasher_id}", payload, headers=headers)

    def list_dasher_earnings(self, dasher_id, headers, params=None):
        return self._request("GET", f"/dashers/{dasher_id}/earnings", headers=headers, params=params)

    # -----------------------------------------------------------------
    # Order
    # -----------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_line_item(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/line-items", payload, headers=headers)

    def list_line_items(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/line-items", headers=headers, params=params)

    def list_order_deliveries(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/deliveries", headers=headers, params=params)

    def list_order_tip_adjustments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/tip-adjustments", headers=headers, params=params)

    def list_order_issues(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/issues", headers=headers, params=params)

    def release_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/release", {}, headers=headers)

    def dispatch_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/dispatch", payload, headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers=headers)

    def adjust_tip(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/tip-adjustments", payload, headers=headers)

    def file_issue(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/issues", payload, headers=headers)

    # -----------------------------------------------------------------
    # Delivery
    # -----------------------------------------------------------------
    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def accept_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/accept", {}, headers=headers)

    def decline_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/decline", {}, headers=headers)

    def pickup_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/picked-up", {}, headers=headers)

    def deliver_delivery(self, delivery_id, headers):
        return self._request("POST", f"/deliveries/{delivery_id}/delivered", {}, headers=headers)

    def list_delivery_earnings(self, delivery_id, headers, params=None):
        return self._request("GET", f"/deliveries/{delivery_id}/earnings", headers=headers, params=params)

    # -----------------------------------------------------------------
    # OrderIssue
    # -----------------------------------------------------------------
    def list_issues(self, headers, params=None):
        return self._request("GET", "/order-issues", headers=headers, params=params)

    def get_issue(self, issue_id, headers):
        return self._request("GET", f"/order-issues/{issue_id}", headers=headers)

    def approve_issue(self, issue_id, headers):
        return self._request("POST", f"/order-issues/{issue_id}/approve", {}, headers=headers)

    def reject_issue(self, issue_id, headers):
        return self._request("POST", f"/order-issues/{issue_id}/reject", {}, headers=headers)

    # -----------------------------------------------------------------
    # EarningsRecord
    # -----------------------------------------------------------------
    def get_earnings_record(self, earnings_id, headers):
        return self._request("GET", f"/earnings-records/{earnings_id}", headers=headers)

    # -----------------------------------------------------------------
    # Test-driving clock
    # -----------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
