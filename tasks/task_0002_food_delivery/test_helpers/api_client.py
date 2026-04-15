"""API client: one method per endpoint from scaffold Table 5."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Food Delivery Platform API client with one method per endpoint."""

    # ── Restaurant Management ──────────────────────────────────────────
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/platform/restaurants", payload, headers)

    def list_restaurants(self, headers, params=None):
        return self._request("GET", "/platform/restaurants", headers=headers, params=params)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/platform/restaurants/{restaurant_id}", headers=headers)

    def update_restaurant(self, restaurant_id, payload, headers):
        return self._request("PATCH", f"/platform/restaurants/{restaurant_id}", payload, headers)

    def approve_restaurant(self, restaurant_id, headers):
        return self._request("POST", f"/platform/restaurants/{restaurant_id}/approve", headers=headers)

    def suspend_restaurant(self, restaurant_id, headers):
        return self._request("POST", f"/platform/restaurants/{restaurant_id}/suspend", headers=headers)

    def reinstate_restaurant(self, restaurant_id, headers):
        return self._request("POST", f"/platform/restaurants/{restaurant_id}/reinstate", headers=headers)

    def close_restaurant(self, restaurant_id, headers):
        return self._request("POST", f"/platform/restaurants/{restaurant_id}/close", headers=headers)

    # ── Menu Items ─────────────────────────────────────────────────────
    def create_menu_item(self, restaurant_id, payload, headers):
        return self._request("POST", f"/platform/restaurants/{restaurant_id}/menu-items", payload, headers)

    def list_menu_items(self, restaurant_id, headers, params=None):
        return self._request("GET", f"/platform/restaurants/{restaurant_id}/menu-items", headers=headers, params=params)

    def update_menu_item(self, restaurant_id, menu_item_id, payload, headers):
        return self._request("PATCH", f"/platform/restaurants/{restaurant_id}/menu-items/{menu_item_id}", payload, headers)

    # ── Customer Management ────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/platform/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/platform/customers/{customer_id}", headers=headers)

    def update_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/platform/customers/{customer_id}", payload, headers)

    def top_up_wallet(self, customer_id, payload, headers):
        return self._request("POST", f"/platform/customers/{customer_id}/wallet/top-up", payload, headers)

    # ── Rider Management ───────────────────────────────────────────────
    def create_rider(self, payload, headers):
        return self._request("POST", "/platform/riders", payload, headers)

    def list_riders(self, headers, params=None):
        return self._request("GET", "/platform/riders", headers=headers, params=params)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/platform/riders/{rider_id}", headers=headers)

    def update_rider(self, rider_id, payload, headers):
        return self._request("PATCH", f"/platform/riders/{rider_id}", payload, headers)

    def approve_rider(self, rider_id, headers):
        return self._request("POST", f"/platform/riders/{rider_id}/approve", headers=headers)

    def suspend_rider(self, rider_id, headers):
        return self._request("POST", f"/platform/riders/{rider_id}/suspend", headers=headers)

    def reinstate_rider(self, rider_id, headers):
        return self._request("POST", f"/platform/riders/{rider_id}/reinstate", headers=headers)

    def deactivate_rider(self, rider_id, headers):
        return self._request("POST", f"/platform/riders/{rider_id}/deactivate", headers=headers)

    # ── Orders ─────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/platform/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/platform/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/platform/orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/confirm", headers=headers)

    def start_preparing_order(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/start-preparing", headers=headers)

    def mark_order_ready(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/mark-ready", headers=headers)

    def pickup_order(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/pickup", headers=headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/deliver", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/cancel", headers=headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/reject", headers=headers)

    def platform_cancel_order(self, order_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/platform-cancel", headers=headers)

    # ── Deliveries ─────────────────────────────────────────────────────
    def create_delivery(self, order_id, payload, headers):
        return self._request("POST", f"/platform/orders/{order_id}/deliveries", payload, headers)

    def get_delivery(self, order_id, delivery_id, headers):
        return self._request("GET", f"/platform/orders/{order_id}/deliveries/{delivery_id}", headers=headers)

    def start_delivery(self, order_id, delivery_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/deliveries/{delivery_id}/start", headers=headers)

    def arrive_at_restaurant(self, order_id, delivery_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/deliveries/{delivery_id}/arrive", headers=headers)

    def cancel_delivery(self, order_id, delivery_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/deliveries/{delivery_id}/cancel", headers=headers)

    # ── Ratings ────────────────────────────────────────────────────────
    def create_rating(self, order_id, payload, headers):
        return self._request("POST", f"/platform/orders/{order_id}/ratings", payload, headers)

    def list_ratings(self, order_id, headers):
        return self._request("GET", f"/platform/orders/{order_id}/ratings", headers=headers)

    def publish_rating(self, order_id, rating_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/ratings/{rating_id}/publish", headers=headers)

    def hide_rating(self, order_id, rating_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/ratings/{rating_id}/hide", headers=headers)

    # ── Complaints ─────────────────────────────────────────────────────
    def create_complaint(self, order_id, payload, headers):
        return self._request("POST", f"/platform/orders/{order_id}/complaints", payload, headers)

    def list_complaints(self, order_id, headers):
        return self._request("GET", f"/platform/orders/{order_id}/complaints", headers=headers)

    def assign_complaint(self, order_id, complaint_id, payload, headers):
        return self._request("POST", f"/platform/orders/{order_id}/complaints/{complaint_id}/assign", payload, headers)

    def escalate_complaint(self, order_id, complaint_id, headers):
        return self._request("POST", f"/platform/orders/{order_id}/complaints/{complaint_id}/escalate", headers=headers)

    def resolve_complaint(self, order_id, complaint_id, payload, headers):
        return self._request("POST", f"/platform/orders/{order_id}/complaints/{complaint_id}/resolve", payload, headers)

    # ── Promotions ─────────────────────────────────────────────────────
    def create_promotion(self, payload, headers):
        return self._request("POST", "/platform/promotions", payload, headers)

    def list_promotions(self, headers, params=None):
        return self._request("GET", "/platform/promotions", headers=headers, params=params)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/platform/promotions/{promotion_id}", headers=headers)

    def disable_promotion(self, promotion_id, headers):
        return self._request("POST", f"/platform/promotions/{promotion_id}/disable", headers=headers)

    # ── Surge Zones ────────────────────────────────────────────────────
    def create_surge_zone(self, payload, headers):
        return self._request("POST", "/platform/surge-zones", payload, headers)

    def list_surge_zones(self, headers):
        return self._request("GET", "/platform/surge-zones", headers=headers)

    def update_surge_zone(self, surge_zone_id, payload, headers):
        return self._request("PATCH", f"/platform/surge-zones/{surge_zone_id}", payload, headers)

    # ── Settlements ────────────────────────────────────────────────────
    def run_settlement(self, payload, headers):
        return self._request("POST", "/platform/settlements/run", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/platform/settlements", headers=headers, params=params)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/platform/settlements/{settlement_id}/approve", headers=headers)

    def mark_settlement_paid(self, settlement_id, headers):
        return self._request("POST", f"/platform/settlements/{settlement_id}/mark-paid", headers=headers)


api_client = ApiClient()
