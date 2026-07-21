"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Products & Inventory ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def create_inventory_lot(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/inventory-lots", payload, headers
        )

    def list_inventory_lots(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/products/{product_id}/inventory-lots", headers=headers, params=params
        )

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Commercial accounts ---
    def create_commercial_account(self, payload, headers):
        return self._request("POST", "/commercial-accounts", payload, headers)

    def get_commercial_account(self, account_id, headers):
        return self._request("GET", f"/commercial-accounts/{account_id}", headers=headers)

    def activate_commercial_account(self, account_id, headers):
        return self._request(
            "POST", f"/commercial-accounts/{account_id}/activate", {}, headers
        )

    def hold_commercial_account(self, account_id, headers):
        return self._request(
            "POST", f"/commercial-accounts/{account_id}/hold", {}, headers
        )

    def set_commercial_account_tier(self, account_id, payload, headers):
        return self._request(
            "POST", f"/commercial-accounts/{account_id}/set-tier", payload, headers
        )

    def create_commercial_order(self, account_id, payload, headers):
        return self._request(
            "POST", f"/commercial-accounts/{account_id}/orders", payload, headers
        )

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", {}, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/refund", {}, headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/pause", {}, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    # --- Consultants & bookings ---
    def create_consultant(self, payload, headers):
        return self._request("POST", "/consultants", payload, headers)

    def get_consultant(self, consultant_id, headers):
        return self._request("GET", f"/consultants/{consultant_id}", headers=headers)

    def create_booking(self, consultant_id, payload, headers):
        return self._request(
            "POST", f"/consultants/{consultant_id}/bookings", payload, headers
        )

    def list_consultant_bookings(self, consultant_id, headers, params=None):
        return self._request(
            "GET", f"/consultants/{consultant_id}/bookings", headers=headers, params=params
        )

    def get_consult_booking(self, booking_id, headers):
        return self._request("GET", f"/consult-bookings/{booking_id}", headers=headers)

    def list_consult_bookings(self, headers, params=None):
        return self._request("GET", "/consult-bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/consult-bookings/{booking_id}/confirm", {}, headers)

    def complete_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/consult-bookings/{booking_id}/complete", payload, headers
        )

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/consult-bookings/{booking_id}/cancel", {}, headers)

    # --- Rooms & workshops ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def create_workshop_session(self, payload, headers):
        return self._request("POST", "/workshop-sessions", payload, headers)

    def get_workshop_session(self, session_id, headers):
        return self._request("GET", f"/workshop-sessions/{session_id}", headers=headers)

    def list_workshop_sessions(self, headers, params=None):
        return self._request("GET", "/workshop-sessions", headers=headers, params=params)

    def open_workshop_session(self, session_id, headers):
        return self._request("POST", f"/workshop-sessions/{session_id}/open", {}, headers)

    def cancel_workshop_session(self, session_id, headers):
        return self._request("POST", f"/workshop-sessions/{session_id}/cancel", {}, headers)

    def create_registration(self, session_id, payload, headers):
        return self._request(
            "POST", f"/workshop-sessions/{session_id}/registrations", payload, headers
        )

    def list_session_registrations(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/workshop-sessions/{session_id}/registrations", headers=headers, params=params
        )

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/workshop-registrations/{registration_id}", headers=headers
        )

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/workshop-registrations", headers=headers, params=params)

    def cancel_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/workshop-registrations/{registration_id}/cancel", {}, headers
        )

    # --- Warranty / RMA ---
    def create_rma(self, payload, headers):
        return self._request("POST", "/rmas", payload, headers)

    def get_rma(self, rma_id, headers):
        return self._request("GET", f"/rmas/{rma_id}", headers=headers)

    def list_rmas(self, headers, params=None):
        return self._request("GET", "/rmas", headers=headers, params=params)

    def review_rma(self, rma_id, headers):
        return self._request("POST", f"/rmas/{rma_id}/review", {}, headers)

    def request_info_rma(self, rma_id, payload, headers):
        return self._request("POST", f"/rmas/{rma_id}/request-info", payload, headers)

    def provide_info_rma(self, rma_id, payload, headers):
        return self._request("POST", f"/rmas/{rma_id}/provide-info", payload, headers)

    def approve_rma(self, rma_id, headers):
        return self._request("POST", f"/rmas/{rma_id}/approve", {}, headers)

    def reject_rma(self, rma_id, payload, headers):
        return self._request("POST", f"/rmas/{rma_id}/reject", payload, headers)


api_client = ApiClient()
