"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Stores ──
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # ── Menu items ──
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/menu-items/{item_id}", headers=headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    # ── Modifiers ──
    def create_modifier(self, payload, headers):
        return self._request("POST", "/modifiers", payload, headers)

    def get_modifier(self, modifier_id, headers):
        return self._request("GET", f"/modifiers/{modifier_id}", headers=headers)

    def list_modifiers(self, headers, params=None):
        return self._request("GET", "/modifiers", headers=headers, params=params)

    # ── Pickup slots ──
    def create_pickup_slot(self, payload, headers):
        return self._request("POST", "/pickup-slots", payload, headers)

    def get_pickup_slot(self, slot_id, headers):
        return self._request("GET", f"/pickup-slots/{slot_id}", headers=headers)

    def list_pickup_slots(self, headers, params=None):
        return self._request("GET", "/pickup-slots", headers=headers, params=params)

    def close_pickup_slot(self, slot_id, headers):
        return self._request("POST", f"/pickup-slots/{slot_id}/close", headers=headers)

    # ── Customers ──
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def adjust_wallet(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/customers/{customer_id}/wallet/adjustments", payload, headers
        )

    # ── Loyalty accounts ──
    def list_loyalty_accounts(self, headers, params=None):
        return self._request("GET", "/loyalty-accounts", headers=headers, params=params)

    def get_loyalty_account(self, account_id, headers):
        return self._request("GET", f"/loyalty-accounts/{account_id}", headers=headers)

    # ── Points ledger entries ──
    def create_points_ledger_entry(self, payload, headers):
        return self._request("POST", "/points-ledger-entries", payload, headers)

    def get_points_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/points-ledger-entries/{entry_id}", headers=headers)

    def list_points_ledger_entries(self, headers, params=None):
        return self._request("GET", "/points-ledger-entries", headers=headers, params=params)

    # ── Subscription plans ──
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    # ── Subscriptions ──
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def pay_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/pay", payload, headers
        )

    def lapse_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/lapse", headers=headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", headers=headers)

    # ── Orders ──
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def update_order_line(self, line_id, payload, headers):
        return self._request("PATCH", f"/order-lines/{line_id}", payload, headers)

    def place_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/place", payload, headers)

    def advance_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/advance", headers=headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/complete", headers=headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    def make_it_right(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/make-it-right", payload, headers)

    # ── Loyalty challenges ──
    def create_loyalty_challenge(self, payload, headers):
        return self._request("POST", "/loyalty-challenges", payload, headers)

    def get_loyalty_challenge(self, challenge_id, headers):
        return self._request("GET", f"/loyalty-challenges/{challenge_id}", headers=headers)

    def list_loyalty_challenges(self, headers, params=None):
        return self._request("GET", "/loyalty-challenges", headers=headers, params=params)

    def start_challenge_round(self, challenge_id, headers):
        return self._request(
            "POST", f"/loyalty-challenges/{challenge_id}/start-round", headers=headers
        )

    def expire_challenge(self, challenge_id, headers):
        return self._request(
            "POST", f"/loyalty-challenges/{challenge_id}/expire", headers=headers
        )

    # ── Test-driving endpoints ──
    def inject_place_n_orders(self, payload, headers):
        return self._request("POST", "/_inject/place_n_orders", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
