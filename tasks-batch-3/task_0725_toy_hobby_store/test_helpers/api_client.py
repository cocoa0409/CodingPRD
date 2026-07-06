"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def update_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/products/{product_id}", payload, headers)

    def activate_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/activate", {}, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", {}, headers)

    # --- Stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # --- Inventory ---
    def create_inventory(self, payload, headers):
        return self._request("POST", "/inventory", payload, headers)

    def list_inventory(self, headers, params=None):
        return self._request("GET", "/inventory", headers=headers, params=params)

    def get_inventory(self, inventory_item_id, headers):
        return self._request("GET", f"/inventory/{inventory_item_id}", headers=headers)

    def receive_inventory(self, inventory_item_id, payload, headers):
        return self._request("POST", f"/inventory/{inventory_item_id}/receive", payload, headers)

    # --- Allocations ---
    def create_allocation(self, payload, headers):
        return self._request("POST", "/allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/release", {}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def mark_ready_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/mark-ready", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # --- Layaways ---
    def create_layaway(self, payload, headers):
        return self._request("POST", "/layaways", payload, headers)

    def list_layaways(self, headers, params=None):
        return self._request("GET", "/layaways", headers=headers, params=params)

    def get_layaway(self, layaway_id, headers):
        return self._request("GET", f"/layaways/{layaway_id}", headers=headers)

    def pay_layaway(self, layaway_id, payload, headers):
        return self._request("POST", f"/layaways/{layaway_id}/payments", payload, headers)

    def cancel_layaway(self, layaway_id, headers):
        return self._request("POST", f"/layaways/{layaway_id}/cancel", {}, headers)

    # --- Special Orders ---
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, special_order_id, headers):
        return self._request("GET", f"/special-orders/{special_order_id}", headers=headers)

    def quote_special_order(self, special_order_id, payload, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/quotes", payload, headers)

    def approve_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/approve", {}, headers)

    def convert_special_order(self, special_order_id, headers):
        return self._request("POST", f"/special-orders/{special_order_id}/convert", {}, headers)

    # --- Recalls ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/recalls", payload, headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/recalls", headers=headers, params=params)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/recalls/{recall_id}", headers=headers)

    def issue_recall(self, recall_id, headers, payload=None):
        return self._request("POST", f"/recalls/{recall_id}/issue", payload or {}, headers)

    # --- Demo Events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def register_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/register", payload, headers)

    # --- Gift Registry / Wishlist ---
    def create_registry(self, payload, headers):
        return self._request("POST", "/registries", payload, headers)

    def list_registries(self, headers, params=None):
        return self._request("GET", "/registries", headers=headers, params=params)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"/registries/{registry_id}", headers=headers)

    def add_registry_item(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/items", payload, headers)

    def list_registry_items_in_registry(self, registry_id, headers, params=None):
        return self._request("GET", f"/registries/{registry_id}/items", headers=headers, params=params)

    def list_registry_items(self, headers, params=None):
        return self._request("GET", "/registry-items", headers=headers, params=params)

    def get_registry_item(self, registry_item_id, headers):
        return self._request("GET", f"/registry-items/{registry_item_id}", headers=headers)

    def close_registry(self, registry_id, headers):
        return self._request("POST", f"/registries/{registry_id}/close", {}, headers)

    # --- Returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def approve_return(self, return_id, payload, headers):
        return self._request("POST", f"/returns/{return_id}/approve", payload, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
