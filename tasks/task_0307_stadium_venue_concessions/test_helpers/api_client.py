"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ Venue
    def create_venue(self, payload, headers):
        return self._request("POST", "/concessions/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/concessions/venues/{venue_id}", headers=headers)

    # ---------------------------------------------------------------- Product
    def create_product(self, payload, headers):
        return self._request("POST", "/concessions/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/concessions/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/concessions/products", headers=headers, params=params)

    # ------------------------------------------------------------------ Event
    def create_event(self, payload, headers):
        return self._request("POST", "/concessions/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/concessions/events/{event_id}", headers=headers)

    def list_venue_events(self, venue_id, headers, params=None):
        return self._request("GET", f"/concessions/venues/{venue_id}/events", headers=headers, params=params)

    def open_doors(self, event_id, headers):
        return self._request("POST", f"/concessions/events/{event_id}/open-doors", {}, headers)

    def open_peak_window(self, event_id, headers):
        return self._request("POST", f"/concessions/events/{event_id}/peak-window/open", {}, headers)

    def close_peak_window(self, event_id, headers):
        return self._request("POST", f"/concessions/events/{event_id}/peak-window/close", {}, headers)

    def settle_event(self, event_id, headers):
        return self._request("POST", f"/concessions/events/{event_id}/settle", {}, headers)

    def get_revenue_share_statement(self, event_id, headers):
        return self._request("GET", f"/concessions/events/{event_id}/revenue-share-statement", headers=headers)

    # ------------------------------------------------------------------ Stand
    def create_stand(self, payload, headers):
        return self._request("POST", "/concessions/stands", payload, headers)

    def get_stand(self, stand_id, headers):
        return self._request("GET", f"/concessions/stands/{stand_id}", headers=headers)

    def list_event_stands(self, event_id, headers, params=None):
        return self._request("GET", f"/concessions/events/{event_id}/stands", headers=headers, params=params)

    def open_stand(self, stand_id, headers):
        return self._request("POST", f"/concessions/stands/{stand_id}/open", {}, headers)

    def suspend_stand(self, stand_id, headers):
        return self._request("POST", f"/concessions/stands/{stand_id}/suspend", {}, headers)

    def close_stand(self, stand_id, headers):
        return self._request("POST", f"/concessions/stands/{stand_id}/close", {}, headers)

    def expire_lots(self, stand_id, headers):
        return self._request("POST", f"/concessions/stands/{stand_id}/expire-lots", {}, headers)

    def get_replenishment_suggestions(self, stand_id, headers):
        return self._request("GET", f"/concessions/stands/{stand_id}/replenishment-suggestions", headers=headers)

    # --------------------------------------------------------------- MenuItem
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/concessions/menu-items", payload, headers)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/concessions/menu-items/{menu_item_id}", headers=headers)

    def list_stand_menu_items(self, stand_id, headers, params=None):
        return self._request("GET", f"/concessions/stands/{stand_id}/menu-items", headers=headers, params=params)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/concessions/menu-items", headers=headers, params=params)

    # ----------------------------------------------------------- InventoryLot
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/concessions/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/concessions/inventory-lots/{lot_id}", headers=headers)

    def list_stand_inventory_lots(self, stand_id, headers, params=None):
        return self._request("GET", f"/concessions/stands/{stand_id}/inventory-lots", headers=headers, params=params)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/concessions/inventory-lots", headers=headers, params=params)

    # ---------------------------------------------------------- Replenishment
    def create_replenishment(self, payload, headers):
        return self._request("POST", "/concessions/replenishments", payload, headers)

    def get_replenishment(self, replenishment_id, headers):
        return self._request("GET", f"/concessions/replenishments/{replenishment_id}", headers=headers)

    def list_replenishments(self, headers, params=None):
        return self._request("GET", "/concessions/replenishments", headers=headers, params=params)

    def pick_replenishment(self, replenishment_id, headers):
        return self._request("POST", f"/concessions/replenishments/{replenishment_id}/pick", {}, headers)

    def deliver_replenishment(self, replenishment_id, payload, headers):
        return self._request("POST", f"/concessions/replenishments/{replenishment_id}/deliver", payload, headers)

    def cancel_replenishment(self, replenishment_id, headers):
        return self._request("POST", f"/concessions/replenishments/{replenishment_id}/cancel", {}, headers)

    # --------------------------------------------------------------- Transfer
    def create_transfer(self, payload, headers):
        return self._request("POST", "/concessions/transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/concessions/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/concessions/transfers", headers=headers, params=params)

    def dispatch_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/concessions/transfers/{transfer_id}/dispatch", payload, headers)

    def complete_transfer(self, transfer_id, headers):
        return self._request("POST", f"/concessions/transfers/{transfer_id}/complete", {}, headers)

    def cancel_transfer(self, transfer_id, headers):
        return self._request("POST", f"/concessions/transfers/{transfer_id}/cancel", {}, headers)

    # ------------------------------------------------------------ WasteRecord
    def create_waste_record(self, payload, headers):
        return self._request("POST", "/concessions/waste-records", payload, headers)

    def get_waste_record(self, waste_record_id, headers):
        return self._request("GET", f"/concessions/waste-records/{waste_record_id}", headers=headers)

    def list_waste_records(self, headers, params=None):
        return self._request("GET", "/concessions/waste-records", headers=headers, params=params)

    # -------------------------------------------------------- Order/OrderLine
    def create_order(self, payload, headers):
        return self._request("POST", "/concessions/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/concessions/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/concessions/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/concessions/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/concessions/orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/concessions/order-lines/{order_line_id}", headers=headers)

    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", "/concessions/order-lines", headers=headers, params=params)

    def place_order(self, order_id, headers):
        return self._request("POST", f"/concessions/orders/{order_id}/place", {}, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/concessions/orders/{order_id}/pay", {}, headers)

    def ready_order(self, order_id, payload, headers):
        return self._request("POST", f"/concessions/orders/{order_id}/ready", payload, headers)

    def pickup_order(self, order_id, headers):
        return self._request("POST", f"/concessions/orders/{order_id}/pickup", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/concessions/orders/{order_id}/cancel", {}, headers)

    # ----------------------------------------------------------------- Patron
    def create_patron(self, payload, headers):
        return self._request("POST", "/concessions/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/concessions/patrons/{patron_id}", headers=headers)

    # ------------------------------------------------------------- StaffShift
    def create_staff_shift(self, payload, headers):
        return self._request("POST", "/concessions/staff-shifts", payload, headers)

    def get_staff_shift(self, shift_id, headers):
        return self._request("GET", f"/concessions/staff-shifts/{shift_id}", headers=headers)

    def list_stand_staff_shifts(self, stand_id, headers, params=None):
        return self._request("GET", f"/concessions/stands/{stand_id}/staff-shifts", headers=headers, params=params)

    def check_in_shift(self, shift_id, headers):
        return self._request("POST", f"/concessions/staff-shifts/{shift_id}/check-in", {}, headers)

    def check_out_shift(self, shift_id, headers):
        return self._request("POST", f"/concessions/staff-shifts/{shift_id}/check-out", {}, headers)

    def cancel_staff_shift(self, shift_id, headers):
        return self._request("POST", f"/concessions/staff-shifts/{shift_id}/cancel", {}, headers)

    # --------------------------------------------------------- Test-driving clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------ Raw header escape hatch
    def request_no_auth(self, method, path):
        """Issue a request with no auth headers (for ERR_UNAUTHENTICATED tests)."""
        return self._request(method, path, headers={})


api_client = ApiClient()
