"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Franchisees / Stores / Vehicles ---
    def create_franchisee(self, payload, headers):
        return self._request("POST", "/franchisees", payload, headers)

    def get_franchisee(self, franchisee_id, headers):
        return self._request("GET", f"/franchisees/{franchisee_id}", headers=headers)

    def list_franchisee_stores(self, franchisee_id, headers, params=None):
        return self._request("GET", f"/franchisees/{franchisee_id}/stores", headers=headers, params=params)

    def create_store(self, franchisee_id, payload, headers):
        return self._request("POST", f"/franchisees/{franchisee_id}/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def update_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    def create_delivery_vehicle(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/delivery-vehicles", payload, headers)

    def list_delivery_vehicles(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/delivery-vehicles", headers=headers, params=params)

    def update_delivery_vehicle(self, vehicle_id, payload, headers):
        return self._request("PATCH", f"/delivery-vehicles/{vehicle_id}", payload, headers)

    # --- Ingredients / Inventory ---
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/ingredients", headers=headers, params=params)

    def create_inventory_lot(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def spoilage_sweep(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/spoilage-sweep", {}, headers)

    # --- Menu / Boosts ---
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def create_boost(self, payload, headers):
        return self._request("POST", "/boosts", payload, headers)

    def list_boosts(self, headers, params=None):
        return self._request("GET", "/boosts", headers=headers, params=params)

    # --- Customers / Subscriptions / Loyalty ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_subscription(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/subscriptions", payload, headers)

    def list_subscriptions(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def renew_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/renew", payload, headers)

    def change_plan(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/change-plan", payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    def list_customer_points_transactions(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/points-transactions", headers=headers, params=params)

    def list_order_points_transactions(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/points-transactions", headers=headers, params=params)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def ready_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ready", {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/complete", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # --- Catering ---
    def create_catering_booking(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/catering-bookings", payload, headers)

    def get_catering_booking(self, booking_id, headers):
        return self._request("GET", f"/catering-bookings/{booking_id}", headers=headers)

    def list_catering_bookings(self, headers, params=None):
        return self._request("GET", "/catering-bookings", headers=headers, params=params)

    def confirm_catering_booking(self, booking_id, headers):
        return self._request("POST", f"/catering-bookings/{booking_id}/confirm", {}, headers)

    def cancel_catering_booking(self, booking_id, headers):
        return self._request("POST", f"/catering-bookings/{booking_id}/cancel", {}, headers)

    def complete_catering_booking(self, booking_id, headers):
        return self._request("POST", f"/catering-bookings/{booking_id}/complete", {}, headers)

    # --- Reconciliation ---
    def create_reconciliation(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/reconciliations", payload, headers)

    def list_reconciliations(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/reconciliations", headers=headers, params=params)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request("GET", f"/reconciliations/{reconciliation_id}", headers=headers)

    def count_reconciliation(self, reconciliation_id, payload, headers):
        return self._request("POST", f"/reconciliations/{reconciliation_id}/count", payload, headers)

    def post_reconciliation(self, reconciliation_id, payload, headers):
        return self._request("POST", f"/reconciliations/{reconciliation_id}/post", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
