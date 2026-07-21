"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    # --- Products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    def add_component(self, product_id, payload, headers):
        return self._request("POST", f"/api/products/{product_id}/components", payload, headers)

    def list_components(self, product_id, headers, params=None):
        return self._request("GET", f"/api/products/{product_id}/components",
                             headers=headers, params=params)

    # --- Fusti ---
    def create_fusti(self, payload, headers):
        return self._request("POST", "/api/fusti", payload, headers)

    def get_fusti(self, fusti_id, headers):
        return self._request("GET", f"/api/fusti/{fusti_id}", headers=headers)

    def list_fusti(self, headers, params=None):
        return self._request("GET", "/api/fusti", headers=headers, params=params)

    def transition_fusti(self, fusti_id, payload, headers):
        return self._request("POST", f"/api/fusti/{fusti_id}/transition", payload, headers)

    # --- Reservations ---
    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/api/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/api/reservations", headers=headers, params=params)

    # --- Replenishment orders ---
    def get_replenishment_order(self, ro_id, headers):
        return self._request("GET", f"/api/replenishment-orders/{ro_id}", headers=headers)

    def list_replenishment_orders(self, headers, params=None):
        return self._request("GET", "/api/replenishment-orders", headers=headers, params=params)

    def receive_replenishment(self, ro_id, payload, headers):
        return self._request("POST", f"/api/replenishment-orders/{ro_id}/receive", payload, headers)

    # --- Wholesale accounts ---
    def create_wholesale_account(self, payload, headers):
        return self._request("POST", "/api/wholesale-accounts", payload, headers)

    def get_wholesale_account(self, wa_id, headers):
        return self._request("GET", f"/api/wholesale-accounts/{wa_id}", headers=headers)

    def list_wholesale_accounts(self, headers, params=None):
        return self._request("GET", "/api/wholesale-accounts", headers=headers, params=params)

    def submit_wholesale_account(self, wa_id, headers):
        return self._request("POST", f"/api/wholesale-accounts/{wa_id}/submit", {}, headers)

    def decide_wholesale_account(self, wa_id, payload, headers):
        return self._request("POST", f"/api/wholesale-accounts/{wa_id}/decision", payload, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/pay", payload, headers)

    def fulfill_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/fulfill", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", payload, headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/api/subscriptions", payload, headers)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/api/subscriptions/{sub_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/api/subscriptions", headers=headers, params=params)

    def transition_subscription(self, sub_id, payload, headers):
        return self._request("POST", f"/api/subscriptions/{sub_id}/transition", payload, headers)

    # --- Tasting bar ---
    def create_tasting_station(self, payload, headers):
        return self._request("POST", "/api/tasting-stations", payload, headers)

    def create_tasting_session(self, payload, headers):
        return self._request("POST", "/api/tasting-sessions", payload, headers)

    def get_tasting_session(self, session_id, headers):
        return self._request("GET", f"/api/tasting-sessions/{session_id}", headers=headers)

    def list_tasting_sessions(self, headers, params=None):
        return self._request("GET", "/api/tasting-sessions", headers=headers, params=params)

    def transition_tasting_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/tasting-sessions/{session_id}/transition", payload, headers)


api_client = ApiClient()
