"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Members ──────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def close_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/close", {}, headers)

    def get_member_card(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}/card", headers=headers)

    def update_member_card(self, member_id, payload, headers):
        return self._request("PATCH", f"/members/{member_id}/card", payload, headers)

    def reload_card(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/card/reload", payload, headers)

    # ─── Wallet transactions ──────────────────────────────────────────────
    def list_wallet_transactions(self, headers, params=None):
        return self._request("GET", "/wallet-transactions", headers=headers, params=params)

    def get_wallet_transaction(self, wallet_transaction_id, headers):
        return self._request("GET", f"/wallet-transactions/{wallet_transaction_id}", headers=headers)

    # ─── Star ledger ──────────────────────────────────────────────────────
    def list_star_ledger_entries(self, headers, params=None):
        return self._request("GET", "/star-ledger-entries", headers=headers, params=params)

    def get_star_ledger_entry(self, star_ledger_entry_id, headers):
        return self._request("GET", f"/star-ledger-entries/{star_ledger_entry_id}", headers=headers)

    # ─── Rewards ──────────────────────────────────────────────────────────
    def redeem_reward(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/rewards/redeem", {}, headers)

    def claim_birthday_reward(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/rewards/birthday", {}, headers)

    def list_rewards(self, headers, params=None):
        return self._request("GET", "/rewards", headers=headers, params=params)

    def get_reward(self, reward_id, headers):
        return self._request("GET", f"/rewards/{reward_id}", headers=headers)

    # ─── Stores & catalog ─────────────────────────────────────────────────
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def pause_store(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/pause", payload, headers)

    def create_menu_item(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/menu-items", payload, headers)

    def list_menu_items(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/menu-items", headers=headers, params=params)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def create_modifier(self, menu_item_id, payload, headers):
        return self._request("POST", f"/menu-items/{menu_item_id}/modifiers", payload, headers)

    def list_modifiers(self, menu_item_id, headers, params=None):
        return self._request("GET", f"/menu-items/{menu_item_id}/modifiers", headers=headers, params=params)

    def create_pickup_slot(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/pickup-slots", payload, headers)

    def list_pickup_slots(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/pickup-slots", headers=headers, params=params)

    def get_pickup_slot(self, pickup_slot_id, headers):
        return self._request("GET", f"/pickup-slots/{pickup_slot_id}", headers=headers)

    # ─── Orders ───────────────────────────────────────────────────────────
    def create_order(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def get_member_order(self, member_id, order_id, headers):
        return self._request("GET", f"/members/{member_id}/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, member_id, order_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def pay_order(self, member_id, order_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/orders/{order_id}/pay", payload, headers)

    def place_order(self, member_id, order_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/orders/{order_id}/place", payload, headers)

    def cancel_order(self, member_id, order_id, headers):
        return self._request("POST", f"/members/{member_id}/orders/{order_id}/cancel", {}, headers)

    # ─── Store-side order ops ─────────────────────────────────────────────
    def start_prep(self, store_id, order_id, headers):
        return self._request("POST", f"/stores/{store_id}/orders/{order_id}/start-prep", {}, headers)

    def mark_ready(self, store_id, order_id, headers):
        return self._request("POST", f"/stores/{store_id}/orders/{order_id}/ready", {}, headers)

    def complete_order(self, store_id, order_id, headers):
        return self._request("POST", f"/stores/{store_id}/orders/{order_id}/complete", {}, headers)

    def refund_order(self, store_id, order_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/orders/{order_id}/refund", payload, headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    # ─── Test-driving clock ───────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
