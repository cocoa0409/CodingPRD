"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---------------------------------------------------------
    def create_customer(self, payload, headers=None):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/orders", headers=headers, params=params)

    # --- Stores ------------------------------------------------------------
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers=headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_store_pickup_slots(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/pickup-slots", headers=headers, params=params)

    def list_store_inventory(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/inventory", headers=headers, params=params)

    def list_store_curbside_checkins(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/curbside-checkins", headers=headers, params=params)

    def list_store_holds(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/holds", headers=headers, params=params)

    # --- Products ----------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # --- Store inventory ---------------------------------------------------
    def create_store_inventory(self, payload, headers):
        return self._request("POST", "/store-inventory", payload, headers=headers)

    def list_store_inventory_filtered(self, headers, params=None):
        return self._request("GET", "/store-inventory", headers=headers, params=params)

    def get_store_inventory(self, inventory_id, headers):
        return self._request("GET", f"/store-inventory/{inventory_id}", headers=headers)

    def list_inventory_movements(self, inventory_id, headers, params=None):
        return self._request("GET", f"/store-inventory/{inventory_id}/movements", headers=headers, params=params)

    def restock_inventory(self, inventory_id, payload, headers):
        return self._request("POST", f"/store-inventory/{inventory_id}/restock", payload, headers=headers)

    # --- Pickup slots ------------------------------------------------------
    def create_pickup_slot(self, payload, headers):
        return self._request("POST", "/pickup-slots", payload, headers=headers)

    def get_pickup_slot(self, slot_id, headers):
        return self._request("GET", f"/pickup-slots/{slot_id}", headers=headers)

    # --- Orders ------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def list_order_pickup_events(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/pickup-events", headers=headers, params=params)

    def list_order_holds(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/holds", headers=headers, params=params)

    def list_order_curbside_checkins(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/curbside-checkins", headers=headers, params=params)

    def submit_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/submit", payload, headers=headers)

    def start_picking(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/start-picking", {}, headers=headers)

    def stage_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/stage", {}, headers=headers)

    def ready_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ready", {}, headers=headers)

    def verify_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/verify", payload, headers=headers)

    def pickup_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pickup", payload, headers=headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/close", {}, headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers=headers)

    def expire_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/expire", {}, headers=headers)

    # --- Order lines -------------------------------------------------------
    def list_order_lines_filtered(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_line_pickup_events(self, line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{line_id}/pickup-events", headers=headers, params=params)

    def pick_line(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/pick", payload, headers=headers)

    def abandon_line(self, line_id, headers):
        return self._request("POST", f"/order-lines/{line_id}/abandon", {}, headers=headers)

    def list_line_substitutions(self, line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{line_id}/substitutions", headers=headers, params=params)

    # --- Substitutions -----------------------------------------------------
    def create_substitution(self, payload, headers):
        return self._request("POST", "/substitutions", payload, headers=headers)

    def list_substitutions(self, headers, params=None):
        return self._request("GET", "/substitutions", headers=headers, params=params)

    def get_substitution(self, substitution_id, headers):
        return self._request("GET", f"/substitutions/{substitution_id}", headers=headers)

    def accept_substitution(self, substitution_id, headers):
        return self._request("POST", f"/substitutions/{substitution_id}/accept", {}, headers=headers)

    def decline_substitution(self, substitution_id, headers):
        return self._request("POST", f"/substitutions/{substitution_id}/decline", {}, headers=headers)

    def withdraw_substitution(self, substitution_id, headers):
        return self._request("POST", f"/substitutions/{substitution_id}/withdraw", {}, headers=headers)

    # --- Curbside check-ins ------------------------------------------------
    def create_curbside_checkin(self, payload, headers):
        return self._request("POST", "/curbside-checkins", payload, headers=headers)

    def get_curbside_checkin(self, checkin_id, headers):
        return self._request("GET", f"/curbside-checkins/{checkin_id}", headers=headers)

    def start_loading_checkin(self, checkin_id, headers):
        return self._request("POST", f"/curbside-checkins/{checkin_id}/start-loading", {}, headers=headers)

    def complete_checkin(self, checkin_id, headers):
        return self._request("POST", f"/curbside-checkins/{checkin_id}/complete", {}, headers=headers)

    def cancel_checkin(self, checkin_id, headers):
        return self._request("POST", f"/curbside-checkins/{checkin_id}/cancel", {}, headers=headers)

    # --- Test-driving clock ------------------------------------------------
    def clock_set(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers=headers)

    def clock_advance(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers=headers)


api_client = ApiClient()
