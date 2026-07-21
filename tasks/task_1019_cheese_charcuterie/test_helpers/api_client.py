"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request("POST", f"/api/customers/{customer_id}/set-status", payload, headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    # --- Caves ---
    def create_cave(self, payload, headers):
        return self._request("POST", "/api/caves", payload, headers)

    def get_cave(self, cave_id, headers):
        return self._request("GET", f"/api/caves/{cave_id}", headers=headers)

    def rotate_cave(self, cave_id, headers):
        return self._request("POST", f"/api/caves/{cave_id}/rotate", {}, headers)

    # --- Lots ---
    def receive_lot(self, payload, headers):
        return self._request("POST", "/api/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/api/lots", headers=headers, params=params)

    def discard_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/lots/{lot_id}/discard", payload, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/lines", payload, headers)

    def allocate_order_line(self, line_id, payload, headers):
        return self._request("POST", f"/api/order-lines/{line_id}/allocate", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/api/order-lines", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/submit", {}, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/pay", payload, headers)

    def fulfill_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/fulfill", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    def return_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/return", {}, headers)

    def get_order_label(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/label", headers=headers)

    # --- Boards ---
    def create_board(self, payload, headers):
        return self._request("POST", "/api/boards", payload, headers)

    def get_board(self, board_id, headers):
        return self._request("GET", f"/api/boards/{board_id}", headers=headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/api/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/pause", {}, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/api/subscriptions/{subscription_id}/cancel", {}, headers)

    # --- Prep stations ---
    def create_prep_station(self, payload, headers):
        return self._request("POST", "/api/prep-stations", payload, headers)

    def get_prep_station(self, prep_station_id, headers):
        return self._request("GET", f"/api/prep-stations/{prep_station_id}", headers=headers)

    # --- Tasting rooms & events ---
    def create_tasting_room(self, payload, headers):
        return self._request("POST", "/api/tasting-rooms", payload, headers)

    def get_tasting_room(self, tasting_room_id, headers):
        return self._request("GET", f"/api/tasting-rooms/{tasting_room_id}", headers=headers)

    def create_tasting_event(self, payload, headers):
        return self._request("POST", "/api/tasting-events", payload, headers)

    def get_tasting_event(self, event_id, headers):
        return self._request("GET", f"/api/tasting-events/{event_id}", headers=headers)

    def list_tasting_events(self, headers, params=None):
        return self._request("GET", "/api/tasting-events", headers=headers, params=params)

    def cancel_tasting_event(self, event_id, headers):
        return self._request("POST", f"/api/tasting-events/{event_id}/cancel", {}, headers)


api_client = ApiClient()
