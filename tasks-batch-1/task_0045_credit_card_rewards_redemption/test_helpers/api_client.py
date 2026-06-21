"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clock (test-driving, PRD §3.10) ────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── CardProduct (PRD §3.1) ─────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def retire_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/retire", headers=headers)

    # ─── CashbackCategory (PRD §3.1) ────────────────────────────
    def create_cashback_category(self, payload, headers):
        return self._request("POST", "/cashback-categories", payload, headers)

    def get_cashback_category(self, cat_id, headers):
        return self._request("GET", f"/cashback-categories/{cat_id}", headers=headers)

    def list_cashback_categories(self, headers, params=None):
        return self._request("GET", "/cashback-categories", headers=headers, params=params)

    # ─── QuarterlyCategory (PRD §3.1) ───────────────────────────
    def create_quarterly_category(self, payload, headers):
        return self._request("POST", "/quarterly-categories", payload, headers)

    def get_quarterly_category(self, cat_id, headers):
        return self._request("GET", f"/quarterly-categories/{cat_id}", headers=headers)

    def list_quarterly_categories(self, headers, params=None):
        return self._request("GET", "/quarterly-categories", headers=headers, params=params)

    # ─── TransferPartner (PRD §3.1) ─────────────────────────────
    def create_transfer_partner(self, payload, headers):
        return self._request("POST", "/transfer-partners", payload, headers)

    def get_transfer_partner(self, partner_id, headers):
        return self._request("GET", f"/transfer-partners/{partner_id}", headers=headers)

    def list_transfer_partners(self, headers, params=None):
        return self._request("GET", "/transfer-partners", headers=headers, params=params)

    def suspend_transfer_partner(self, partner_id, headers):
        return self._request(
            "POST", f"/transfer-partners/{partner_id}/suspend", headers=headers
        )

    # ─── CardAccount (PRD §3.2) ─────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def activate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/activate", headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", headers=headers)

    # ─── Transaction (PRD §3.3, §3.4) ───────────────────────────
    def create_transaction(self, payload, headers):
        return self._request("POST", "/transactions", payload, headers)

    def get_transaction(self, txn_id, headers):
        return self._request("GET", f"/transactions/{txn_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    def post_transaction(self, txn_id, headers):
        return self._request("POST", f"/transactions/{txn_id}/post", headers=headers)

    def decline_transaction(self, txn_id, headers):
        return self._request("POST", f"/transactions/{txn_id}/decline", headers=headers)

    def refund_transaction(self, txn_id, headers):
        return self._request("POST", f"/transactions/{txn_id}/refund", headers=headers)

    # ─── PointsLot (read-only, PRD §3.4) ────────────────────────
    def get_points_lot(self, lot_id, headers):
        return self._request("GET", f"/points-lots/{lot_id}", headers=headers)

    def list_points_lots(self, headers, params=None):
        return self._request("GET", "/points-lots", headers=headers, params=params)

    # ─── Redemption (PRD §3.8) ──────────────────────────────────
    def create_redemption(self, payload, headers):
        return self._request("POST", "/redemptions", payload, headers)

    def get_redemption(self, red_id, headers):
        return self._request("GET", f"/redemptions/{red_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/redemptions", headers=headers, params=params)

    def confirm_redemption(self, red_id, headers):
        return self._request("POST", f"/redemptions/{red_id}/confirm", headers=headers)

    def reject_redemption(self, red_id, headers):
        return self._request("POST", f"/redemptions/{red_id}/reject", headers=headers)

    def reverse_redemption(self, red_id, headers):
        return self._request("POST", f"/redemptions/{red_id}/reverse", headers=headers)

    # ─── CategoryActivation (PRD §3.9) ──────────────────────────
    def create_category_activation(self, payload, headers):
        return self._request("POST", "/category-activations", payload, headers)

    def get_category_activation(self, act_id, headers):
        return self._request("GET", f"/category-activations/{act_id}", headers=headers)

    def list_category_activations(self, headers, params=None):
        return self._request("GET", "/category-activations", headers=headers, params=params)

    # ─── Period close (PRD §3.10) ───────────────────────────────
    def close_period(self, headers):
        return self._request("POST", "/close-period", headers=headers)


api_client = ApiClient()
