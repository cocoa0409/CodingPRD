"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def get_customer_risk(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/risk", headers=headers, params=params)

    def mark_dormancy(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/dormancy/mark", {}, headers)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/orders", headers=headers, params=params)

    def list_customer_subscriptions(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/subscriptions", headers=headers, params=params)

    # --- SKUs ---
    def create_sku(self, payload, headers):
        return self._request("POST", "/skus", payload, headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/skus", headers=headers, params=params)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    def approve_label(self, sku_id, headers):
        return self._request("POST", f"/skus/{sku_id}/label/approve", {}, headers)

    def hold_label(self, sku_id, headers):
        return self._request("POST", f"/skus/{sku_id}/label/hold", {}, headers)

    def activate_sku(self, sku_id, headers):
        return self._request("POST", f"/skus/{sku_id}/activate", {}, headers)

    def discontinue_sku(self, sku_id, headers):
        return self._request("POST", f"/skus/{sku_id}/discontinue", {}, headers)

    def list_sku_lots(self, sku_id, headers, params=None):
        return self._request("GET", f"/skus/{sku_id}/lots", headers=headers, params=params)

    # --- Lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def release_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/release", payload, headers)

    def recall_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/recall", {}, headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, sub_id, headers):
        return self._request("GET", f"/subscriptions/{sub_id}", headers=headers)

    def swap_subscription(self, sub_id, payload, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/swap", payload, headers)

    def skip_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/skip", {}, headers)

    def pause_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/pause", {}, headers)

    def resume_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/resume", {}, headers)

    def renew_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/renew", {}, headers)

    def cancel_subscription(self, sub_id, headers):
        return self._request("POST", f"/subscriptions/{sub_id}/cancel", {}, headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines_global(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def reserve_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reserve", {}, headers)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    # --- Bulk quotes ---
    def create_bulk_quote(self, payload, headers):
        return self._request("POST", "/bulk-quotes", payload, headers)

    def get_bulk_quote(self, bq_id, headers):
        return self._request("GET", f"/bulk-quotes/{bq_id}", headers=headers)

    def list_bulk_quotes(self, headers, params=None):
        return self._request("GET", "/bulk-quotes", headers=headers, params=params)

    def quote_bulk_quote(self, bq_id, headers):
        return self._request("POST", f"/bulk-quotes/{bq_id}/quote", {}, headers)

    def accept_bulk_quote(self, bq_id, headers):
        return self._request("POST", f"/bulk-quotes/{bq_id}/accept", {}, headers)

    # --- Referrals & win-back ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def reward_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/reward", {}, headers)

    def void_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/void", {}, headers)

    def create_winback_offer(self, payload, headers):
        return self._request("POST", "/winback-offers", payload, headers)

    def get_winback_offer(self, offer_id, headers):
        return self._request("GET", f"/winback-offers/{offer_id}", headers=headers)

    def list_winback_offers(self, headers, params=None):
        return self._request("GET", "/winback-offers", headers=headers, params=params)

    def redeem_winback_offer(self, offer_id, headers):
        return self._request("POST", f"/winback-offers/{offer_id}/redeem", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
