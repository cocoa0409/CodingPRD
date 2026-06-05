"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def activate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/activate", {}, headers)

    def restrict_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/restrict", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    # --- OptionsApproval ---
    def create_options_approval(self, payload, headers):
        return self._request("POST", "/options-approvals", payload, headers)

    def get_options_approval(self, approval_id, headers):
        return self._request("GET", f"/options-approvals/{approval_id}", headers=headers)

    def list_options_approvals(self, headers, params=None):
        return self._request("GET", "/options-approvals", headers=headers, params=params)

    def submit_options_approval(self, approval_id, headers):
        return self._request("POST", f"/options-approvals/{approval_id}/submit", {}, headers)

    def approve_options_approval(self, approval_id, headers):
        return self._request("POST", f"/options-approvals/{approval_id}/approve", {}, headers)

    def reject_options_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/options-approvals/{approval_id}/reject", payload, headers)

    # --- MarginUpgrade ---
    def create_margin_upgrade(self, payload, headers):
        return self._request("POST", "/margin-upgrades", payload, headers)

    def get_margin_upgrade(self, upgrade_id, headers):
        return self._request("GET", f"/margin-upgrades/{upgrade_id}", headers=headers)

    def list_margin_upgrades(self, headers, params=None):
        return self._request("GET", "/margin-upgrades", headers=headers, params=params)

    def submit_margin_upgrade(self, upgrade_id, headers):
        return self._request("POST", f"/margin-upgrades/{upgrade_id}/submit", {}, headers)

    def approve_margin_upgrade(self, upgrade_id, payload, headers):
        return self._request("POST", f"/margin-upgrades/{upgrade_id}/approve", payload, headers)

    def reject_margin_upgrade(self, upgrade_id, headers):
        return self._request("POST", f"/margin-upgrades/{upgrade_id}/reject", {}, headers)

    # --- Position ---
    def create_position(self, payload, headers):
        return self._request("POST", "/positions", payload, headers)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    def close_position(self, position_id, headers):
        return self._request("POST", f"/positions/{position_id}/close", {}, headers)

    # --- Order ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def accept_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/accept", {}, headers)

    def fill_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fill", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reject", {}, headers)

    # --- DayTrade ---
    def seed_day_trades(self, payload, headers):
        return self._request("POST", "/_day-trades/seed", payload, headers)

    def get_day_trade(self, day_trade_id, headers):
        return self._request("GET", f"/day-trades/{day_trade_id}", headers=headers)

    def list_day_trades(self, headers, params=None):
        return self._request("GET", "/day-trades", headers=headers, params=params)

    # --- AcatTransfer ---
    def create_acat_transfer(self, payload, headers):
        return self._request("POST", "/acat-transfers", payload, headers)

    def get_acat_transfer(self, transfer_id, headers):
        return self._request("GET", f"/acat-transfers/{transfer_id}", headers=headers)

    def list_acat_transfers(self, headers, params=None):
        return self._request("GET", "/acat-transfers", headers=headers, params=params)

    def validate_acat_transfer(self, transfer_id, headers):
        return self._request("POST", f"/acat-transfers/{transfer_id}/validate", {}, headers)

    def settle_acat_transfer(self, transfer_id, headers):
        return self._request("POST", f"/acat-transfers/{transfer_id}/settle", {}, headers)

    def reject_acat_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/acat-transfers/{transfer_id}/reject", payload, headers)

    def cancel_acat_transfer(self, transfer_id, headers):
        return self._request("POST", f"/acat-transfers/{transfer_id}/cancel", {}, headers)


api_client = ApiClient()
