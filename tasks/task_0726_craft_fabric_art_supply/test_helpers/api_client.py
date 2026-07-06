"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def get_loyalty_account(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}/loyalty-account", headers=headers)

    # --- Product / Inventory ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def create_inventory_lot(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/inventory-lots", payload, headers)

    def list_inventory_lots_by_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}/inventory-lots", headers=headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    # --- Coupon ---
    def create_coupon(self, payload, headers):
        return self._request("POST", "/coupons", payload, headers)

    def list_coupons(self, headers, params=None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    # --- Order ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines_by_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def record_cut(self, line_id, payload, headers):
        return self._request("PATCH", f"/order-lines/{line_id}/record-cut", payload, headers)

    def apply_coupon(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/coupons", payload, headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def ready_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ready", {}, headers)

    def pickup_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pickup", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # --- Room ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # --- Workshop ---
    def create_workshop(self, payload, headers):
        return self._request("POST", "/workshops", payload, headers)

    def list_workshops(self, headers, params=None):
        return self._request("GET", "/workshops", headers=headers, params=params)

    def get_workshop(self, workshop_id, headers):
        return self._request("GET", f"/workshops/{workshop_id}", headers=headers)

    def open_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/open", {}, headers)

    def close_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/close", {}, headers)

    def cancel_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/cancel", {}, headers)

    def create_session(self, workshop_id, payload, headers):
        return self._request("POST", f"/workshops/{workshop_id}/sessions", payload, headers)

    def list_sessions_by_workshop(self, workshop_id, headers):
        return self._request("GET", f"/workshops/{workshop_id}/sessions", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/workshop-sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/workshop-sessions/{session_id}", headers=headers)

    def register_workshop(self, workshop_id, payload, headers):
        return self._request("POST", f"/workshops/{workshop_id}/register", payload, headers)

    def list_registrations_by_workshop(self, workshop_id, headers):
        return self._request("GET", f"/workshops/{workshop_id}/registrations", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/workshop-registrations", headers=headers, params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/workshop-registrations/{registration_id}", headers=headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/workshop-registrations/{registration_id}/cancel", {}, headers)

    # --- FramingOrder ---
    def create_framing_order(self, payload, headers):
        return self._request("POST", "/framing-orders", payload, headers)

    def list_framing_orders(self, headers, params=None):
        return self._request("GET", "/framing-orders", headers=headers, params=params)

    def get_framing_order(self, framing_id, headers):
        return self._request("GET", f"/framing-orders/{framing_id}", headers=headers)

    def approve_framing(self, framing_id, headers):
        return self._request("POST", f"/framing-orders/{framing_id}/approve", {}, headers)

    def start_framing(self, framing_id, headers):
        return self._request("POST", f"/framing-orders/{framing_id}/start", {}, headers)

    def complete_framing(self, framing_id, headers):
        return self._request("POST", f"/framing-orders/{framing_id}/complete", {}, headers)

    def cancel_framing(self, framing_id, headers):
        return self._request("POST", f"/framing-orders/{framing_id}/cancel", {}, headers)

    # --- ProjectBundle ---
    def create_project_bundle(self, payload, headers):
        return self._request("POST", "/project-bundles", payload, headers)

    def list_project_bundles(self, headers, params=None):
        return self._request("GET", "/project-bundles", headers=headers, params=params)

    def get_project_bundle(self, bundle_id, headers):
        return self._request("GET", f"/project-bundles/{bundle_id}", headers=headers)

    # --- SpecialOrder ---
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)

    def quote_special_order(self, special_order_id, payload, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/quote", payload, headers)

    def confirm_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/confirm", {}, headers)

    def receive_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/receive", {}, headers)

    def cancel_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/cancel", {}, headers)


api_client = ApiClient()
