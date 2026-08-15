"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Customers -----
    def create_customer(self, payload, headers):
        return self._request("POST", "/margin/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/margin/customers/{customer_id}", headers=headers)

    # ----- Account applications -----
    def create_account_application(self, payload, headers):
        return self._request("POST", "/margin/account-applications", payload, headers)

    def get_account_application(self, application_id, headers):
        return self._request(
            "GET", f"/margin/account-applications/{application_id}", headers=headers
        )

    def list_account_applications(self, headers, params=None):
        return self._request(
            "GET", "/margin/account-applications", headers=headers, params=params
        )

    def review_application(self, application_id, headers):
        return self._request(
            "POST", f"/margin/account-applications/{application_id}/review", {}, headers
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/margin/account-applications/{application_id}/approve", {}, headers
        )

    def reject_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/margin/account-applications/{application_id}/reject", payload, headers
        )

    def resubmit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/margin/account-applications/{application_id}/resubmit", payload, headers
        )

    # ----- Margin accounts -----
    def get_account(self, account_id, headers):
        return self._request("GET", f"/margin/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/margin/accounts", headers=headers, params=params)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/margin/accounts/{account_id}/close", {}, headers)

    # ----- Security profiles -----
    def create_security_profile(self, payload, headers):
        return self._request("POST", "/margin/security-profiles", payload, headers)

    def get_security_profile(self, security_id, headers):
        return self._request(
            "GET", f"/margin/security-profiles/{security_id}", headers=headers
        )

    def list_security_profiles(self, headers, params=None):
        return self._request(
            "GET", "/margin/security-profiles", headers=headers, params=params
        )

    def patch_security_profile(self, security_id, payload, headers):
        return self._request(
            "PATCH", f"/margin/security-profiles/{security_id}", payload, headers
        )

    # ----- Market marks -----
    def post_market_mark(self, payload, headers):
        return self._request("POST", "/margin/market-marks", payload, headers)

    def get_market_mark(self, mark_id, headers):
        return self._request("GET", f"/margin/market-marks/{mark_id}", headers=headers)

    def list_market_marks(self, headers, params=None):
        return self._request("GET", "/margin/market-marks", headers=headers, params=params)

    # ----- Orders / positions / fills / day-trade events -----
    def place_order(self, account_id, payload, headers):
        return self._request(
            "POST", f"/margin/accounts/{account_id}/orders", payload, headers
        )

    def list_account_positions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/margin/accounts/{account_id}/positions", headers=headers, params=params
        )

    def get_position(self, position_id, headers):
        return self._request("GET", f"/margin/positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/margin/positions", headers=headers, params=params)

    def list_account_fills(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/margin/accounts/{account_id}/fills", headers=headers, params=params
        )

    def get_fill(self, fill_id, headers):
        return self._request("GET", f"/margin/fills/{fill_id}", headers=headers)

    def list_fills(self, headers, params=None):
        return self._request("GET", "/margin/fills", headers=headers, params=params)

    def list_account_day_trade_events(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/margin/accounts/{account_id}/day-trade-events",
            headers=headers,
            params=params,
        )

    def get_day_trade_event(self, event_id, headers):
        return self._request(
            "GET", f"/margin/day-trade-events/{event_id}", headers=headers
        )

    def list_day_trade_events(self, headers, params=None):
        return self._request("GET", "/margin/day-trade-events", headers=headers, params=params)

    # ----- Margin calls -----
    def list_account_margin_calls(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/margin/accounts/{account_id}/margin-calls",
            headers=headers,
            params=params,
        )

    def get_margin_call(self, call_id, headers):
        return self._request("GET", f"/margin/margin-calls/{call_id}", headers=headers)

    def waive_margin_call(self, call_id, headers):
        return self._request(
            "POST", f"/margin/margin-calls/{call_id}/waive", {}, headers
        )

    # ----- Liquidation orders -----
    def create_liquidation_order(self, account_id, payload, headers):
        return self._request(
            "POST", f"/margin/accounts/{account_id}/liquidation-orders", payload, headers
        )

    def get_liquidation_order(self, order_id, headers):
        return self._request(
            "GET", f"/margin/liquidation-orders/{order_id}", headers=headers
        )

    def list_liquidation_orders(self, headers, params=None):
        return self._request(
            "GET", "/margin/liquidation-orders", headers=headers, params=params
        )

    def list_call_liquidation_orders(self, call_id, headers, params=None):
        return self._request(
            "GET",
            f"/margin/margin-calls/{call_id}/liquidation-orders",
            headers=headers,
            params=params,
        )

    def fill_liquidation_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/margin/liquidation-orders/{order_id}/fill", payload, headers
        )

    def cancel_liquidation_order(self, order_id, headers):
        return self._request(
            "POST", f"/margin/liquidation-orders/{order_id}/cancel", {}, headers
        )

    # ----- Cash movements -----
    def create_cash_movement(self, account_id, payload, headers):
        return self._request(
            "POST", f"/margin/accounts/{account_id}/cash-movements", payload, headers
        )

    def list_cash_movements(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/margin/accounts/{account_id}/cash-movements",
            headers=headers,
            params=params,
        )

    def get_cash_movement(self, movement_id, headers):
        return self._request(
            "GET", f"/margin/cash-movements/{movement_id}", headers=headers
        )

    # ----- Rate tiers / interest -----
    def create_rate_tier(self, payload, headers):
        return self._request("POST", "/margin/rate-tiers", payload, headers)

    def get_rate_tier(self, tier_id, headers):
        return self._request("GET", f"/margin/rate-tiers/{tier_id}", headers=headers)

    def list_rate_tiers(self, headers, params=None):
        return self._request("GET", "/margin/rate-tiers", headers=headers, params=params)

    def list_interest_entries(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/margin/accounts/{account_id}/interest-entries",
            headers=headers,
            params=params,
        )

    def get_interest_entry(self, entry_id, headers):
        return self._request("GET", f"/margin/interest-entries/{entry_id}", headers=headers)

    def get_interest_summary(self, account_id, headers):
        return self._request(
            "GET", f"/margin/accounts/{account_id}/interest-summary", headers=headers
        )

    # ----- Disputes -----
    def create_dispute(self, payload, headers):
        return self._request("POST", "/margin/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/margin/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/margin/disputes", headers=headers, params=params)

    def list_account_disputes(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/margin/accounts/{account_id}/disputes", headers=headers, params=params
        )

    def start_dispute_review(self, dispute_id, headers):
        return self._request(
            "POST", f"/margin/disputes/{dispute_id}/start-review", {}, headers
        )

    def request_dispute_info(self, dispute_id, headers):
        return self._request(
            "POST", f"/margin/disputes/{dispute_id}/request-info", {}, headers
        )

    def decide_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/margin/disputes/{dispute_id}/decide", payload, headers
        )

    # ----- Test-driving clock / sweep -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/_sweeps/daily", {}, headers)


api_client = ApiClient()
