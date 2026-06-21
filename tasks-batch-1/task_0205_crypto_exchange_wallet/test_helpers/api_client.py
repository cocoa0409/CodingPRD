"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) -------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Accounts / KYC -------------------------------------------------------
    def create_account(self, payload, headers=None):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def create_kyc_application(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/kyc-applications", payload, headers
        )

    def create_kyc_decision(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/kyc-decisions", payload, headers
        )

    def freeze_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/freeze", {}, headers)

    def unfreeze_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/unfreeze", {}, headers)

    # --- Assets / Fee schedules ----------------------------------------------
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def patch_asset(self, asset_id, payload, headers):
        return self._request("PATCH", f"/assets/{asset_id}", payload, headers)

    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # --- Balances / Cost-basis lots ------------------------------------------
    def list_balances(self, headers, params=None):
        return self._request("GET", "/balances", headers=headers, params=params)

    def get_balance(self, balance_id, headers):
        return self._request("GET", f"/balances/{balance_id}", headers=headers)

    def list_cost_basis_lots(self, headers, params=None):
        return self._request(
            "GET", "/cost-basis-lots", headers=headers, params=params
        )

    def get_cost_basis_lot(self, lot_id, headers):
        return self._request("GET", f"/cost-basis-lots/{lot_id}", headers=headers)

    # --- Deposits -------------------------------------------------------------
    def create_deposit(self, payload, headers):
        return self._request("POST", "/deposits", payload, headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def advance_confirmations(self, deposit_id, payload, headers):
        return self._request(
            "POST", f"/deposits/{deposit_id}/confirmations", payload, headers
        )

    def orphan_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/orphan", {}, headers)

    # --- Withdrawal addresses (whitelist) ------------------------------------
    def create_withdrawal_address(self, payload, headers):
        return self._request("POST", "/withdrawal-addresses", payload, headers)

    def list_withdrawal_addresses(self, headers, params=None):
        return self._request(
            "GET", "/withdrawal-addresses", headers=headers, params=params
        )

    def get_withdrawal_address(self, address_id, headers):
        return self._request(
            "GET", f"/withdrawal-addresses/{address_id}", headers=headers
        )

    def activate_withdrawal_address(self, address_id, headers):
        return self._request(
            "POST", f"/withdrawal-addresses/{address_id}/activate", {}, headers
        )

    def remove_withdrawal_address(self, address_id, headers):
        return self._request(
            "DELETE", f"/withdrawal-addresses/{address_id}", headers=headers
        )

    # --- Withdrawals + travel rule -------------------------------------------
    def create_withdrawal(self, payload, headers):
        return self._request("POST", "/withdrawals", payload, headers)

    def list_withdrawals(self, headers, params=None):
        return self._request("GET", "/withdrawals", headers=headers, params=params)

    def get_withdrawal(self, withdrawal_id, headers):
        return self._request("GET", f"/withdrawals/{withdrawal_id}", headers=headers)

    def screen_withdrawal(self, withdrawal_id, headers):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/screen", {}, headers
        )

    def screen_result(self, withdrawal_id, payload, headers):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/screen-result", payload, headers
        )

    def file_travel_rule_record(self, withdrawal_id, payload, headers):
        return self._request(
            "POST",
            f"/withdrawals/{withdrawal_id}/travel-rule-records",
            payload,
            headers,
        )

    def list_travel_rule_records(self, headers, params=None):
        return self._request(
            "GET", "/travel-rule-records", headers=headers, params=params
        )

    def get_travel_rule_record(self, record_id, headers):
        return self._request(
            "GET", f"/travel-rule-records/{record_id}", headers=headers
        )

    def broadcast_withdrawal(self, withdrawal_id, headers):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/broadcast", {}, headers
        )

    def confirm_onchain_withdrawal(self, withdrawal_id, headers):
        return self._request(
            "POST", f"/withdrawals/{withdrawal_id}/confirm-onchain", {}, headers
        )

    # --- Orders & trades ------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def amend_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/orders/{order_id}", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("DELETE", f"/orders/{order_id}", headers=headers)

    def list_trades(self, headers, params=None):
        return self._request("GET", "/trades", headers=headers, params=params)

    def get_trade(self, trade_id, headers):
        return self._request("GET", f"/trades/{trade_id}", headers=headers)

    # --- Staking --------------------------------------------------------------
    def create_staking_position(self, payload, headers):
        return self._request("POST", "/staking-positions", payload, headers)

    def list_staking_positions(self, headers, params=None):
        return self._request(
            "GET", "/staking-positions", headers=headers, params=params
        )

    def get_staking_position(self, position_id, headers):
        return self._request(
            "GET", f"/staking-positions/{position_id}", headers=headers
        )

    def claim_staking_position(self, position_id, headers):
        return self._request(
            "POST", f"/staking-positions/{position_id}/claim", {}, headers
        )

    def unbond_staking_position(self, position_id, headers):
        return self._request(
            "POST", f"/staking-positions/{position_id}/unbond", {}, headers
        )

    def release_staking_position(self, position_id, headers):
        return self._request(
            "POST", f"/staking-positions/{position_id}/release", {}, headers
        )


api_client = ApiClient()
