"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Stores ----
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def lock_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/lock", {}, headers)

    def unlock_store(self, store_id, headers):
        return self._request("POST", f"/stores/{store_id}/unlock", {}, headers)

    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers)

    # ---- Store inventory ----
    def create_store_inventory(self, payload, headers):
        return self._request("POST", "/store-inventory", payload, headers)

    def get_store_inventory(self, inv_id, headers):
        return self._request("GET", f"/store-inventory/{inv_id}", headers=headers)

    def list_store_inventory(self, headers, params=None):
        return self._request("GET", "/store-inventory", headers=headers, params=params)

    def adjust_store_inventory(self, inv_id, payload, headers):
        return self._request("POST", f"/store-inventory/{inv_id}/adjust", payload, headers)

    # ---- Loyalty members ----
    def create_loyalty_member(self, payload, headers):
        return self._request("POST", "/loyalty-members", payload, headers)

    def get_loyalty_member(self, member_id, headers):
        return self._request("GET", f"/loyalty-members/{member_id}", headers=headers)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def capture_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/capture", {}, headers)

    def ready_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ready", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # ---- Order lines (reads) ----
    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    # ---- Assembly crews ----
    def create_assembly_crew(self, payload, headers):
        return self._request("POST", "/assembly-crews", payload, headers)

    def get_assembly_crew(self, crew_id, headers):
        return self._request("GET", f"/assembly-crews/{crew_id}", headers=headers)

    def list_assembly_crews(self, headers, params=None):
        return self._request("GET", "/assembly-crews", headers=headers, params=params)

    # ---- Delivery bookings ----
    def create_delivery_booking(self, payload, headers):
        return self._request("POST", "/delivery-bookings", payload, headers)

    def get_delivery_booking(self, booking_id, headers):
        return self._request("GET", f"/delivery-bookings/{booking_id}", headers=headers)

    def list_delivery_bookings(self, headers, params=None):
        return self._request("GET", "/delivery-bookings", headers=headers, params=params)

    def confirm_delivery_booking(self, booking_id, headers):
        return self._request("POST", f"/delivery-bookings/{booking_id}/confirm", {}, headers)

    def complete_delivery_booking(self, booking_id, headers):
        return self._request("POST", f"/delivery-bookings/{booking_id}/complete", {}, headers)

    def cancel_delivery_booking(self, booking_id, headers):
        return self._request("POST", f"/delivery-bookings/{booking_id}/cancel", {}, headers)

    # ---- Returns ----
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", {}, headers)

    # ---- Registries ----
    def create_registry(self, payload, headers):
        return self._request("POST", "/registries", payload, headers)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"/registries/{registry_id}", headers=headers)

    def list_registries(self, headers, params=None):
        return self._request("GET", "/registries", headers=headers, params=params)

    def add_registry_item(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/items", payload, headers)

    def close_registry(self, registry_id, headers):
        return self._request("POST", f"/registries/{registry_id}/close", {}, headers)

    # ---- Registry items (reads) ----
    def get_registry_item(self, item_id, headers):
        return self._request("GET", f"/registry-items/{item_id}", headers=headers)

    def list_registry_items(self, headers, params=None):
        return self._request("GET", "/registry-items", headers=headers, params=params)

    # ---- Special orders ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, so_id, headers):
        return self._request("GET", f"/special-orders/{so_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def quote_special_order(self, so_id, payload, headers):
        return self._request("POST", f"/special-orders/{so_id}/quote", payload, headers)

    def submit_special_order_for_review(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/submit-for-review", {}, headers)

    def request_special_order_changes(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/request-changes", {}, headers)

    def confirm_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/confirm", {}, headers)

    def cancel_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/cancel", {}, headers)


api_client = ApiClient()
