"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Flavor ----
    def create_flavor(self, payload, headers):
        return self._request("POST", "/flavors", payload, headers)

    def list_flavors(self, headers, params=None):
        return self._request("GET", "/flavors", headers=headers, params=params)

    def get_flavor(self, flavor_id, headers):
        return self._request("GET", f"/flavors/{flavor_id}", headers=headers)

    def update_flavor(self, flavor_id, payload, headers):
        return self._request("PATCH", f"/flavors/{flavor_id}", payload, headers)

    # ---- SizeOption ----
    def create_size_option(self, payload, headers):
        return self._request("POST", "/size-options", payload, headers)

    def list_size_options(self, headers, params=None):
        return self._request("GET", "/size-options", headers=headers, params=params)

    # ---- Topping ----
    def create_topping(self, payload, headers):
        return self._request("POST", "/toppings", payload, headers)

    def list_toppings(self, headers, params=None):
        return self._request("GET", "/toppings", headers=headers, params=params)

    # ---- EventCart / DecoratingStation ----
    def create_event_cart(self, payload, headers):
        return self._request("POST", "/event-carts", payload, headers)

    def create_decorating_station(self, payload, headers):
        return self._request("POST", "/decorating-stations", payload, headers)

    # ---- Batch ----
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/release", {}, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    # ---- WasteEvent ----
    def create_waste_event(self, payload, headers):
        return self._request("POST", "/waste-events", payload, headers)

    def list_waste_events(self, headers, params=None):
        return self._request("GET", "/waste-events", headers=headers, params=params)

    def get_waste_event(self, waste_event_id, headers):
        return self._request("GET", f"/waste-events/{waste_event_id}", headers=headers)

    # ---- LoyaltyAccount ----
    def create_loyalty_account(self, payload, headers):
        return self._request("POST", "/loyalty-accounts", payload, headers)

    def get_loyalty_account(self, account_id, headers):
        return self._request("GET", f"/loyalty-accounts/{account_id}", headers=headers)

    # ---- CashDrawerSession ----
    def create_drawer(self, payload, headers):
        return self._request("POST", "/cash-drawer-sessions", payload, headers)

    def close_drawer(self, drawer_id, payload, headers):
        return self._request("POST", f"/cash-drawer-sessions/{drawer_id}/close", payload, headers)

    def get_drawer(self, drawer_id, headers):
        return self._request("GET", f"/cash-drawer-sessions/{drawer_id}", headers=headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def remove_line(self, order_id, line_id, headers):
        return self._request("DELETE", f"/orders/{order_id}/lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def void_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/void", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/refund", {}, headers)

    # ---- PreOrder ----
    def create_pre_order(self, payload, headers):
        return self._request("POST", "/pre-orders", payload, headers)

    def list_pre_orders(self, headers, params=None):
        return self._request("GET", "/pre-orders", headers=headers, params=params)

    def get_pre_order(self, pre_order_id, headers):
        return self._request("GET", f"/pre-orders/{pre_order_id}", headers=headers)

    def requote_pre_order(self, pre_order_id, payload, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/requote", payload, headers)

    def confirm_pre_order(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/confirm", {}, headers)

    def start_production(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/start-production", {}, headers)

    def request_revision(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/request-revision", {}, headers)

    def fulfill_pre_order(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/fulfill", {}, headers)

    def cancel_pre_order(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/cancel", {}, headers)

    # ---- CateringBooking ----
    def create_catering_booking(self, payload, headers):
        return self._request("POST", "/catering-bookings", payload, headers)

    def list_catering_bookings(self, headers, params=None):
        return self._request("GET", "/catering-bookings", headers=headers, params=params)

    def get_catering_booking(self, booking_id, headers):
        return self._request("GET", f"/catering-bookings/{booking_id}", headers=headers)

    def close_catering_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/catering-bookings/{booking_id}/close", payload, headers)

    def cancel_catering_booking(self, booking_id, headers):
        return self._request("POST", f"/catering-bookings/{booking_id}/cancel", {}, headers)


api_client = ApiClient()
