"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; only the brokerage-specific
endpoint methods are declared here. The base _request() handles envelope
construction, headers, and HTTP transport.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Account ----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def set_compliance_hold(self, account_id, payload, headers):
        return self._request("PATCH", f"/accounts/{account_id}/compliance-hold", payload, headers)

    # ---- Deposit ----
    def create_deposit(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/deposits", payload, headers)

    def list_deposits(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/deposits", headers=headers, params=params)

    def reverse_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/reverse", headers=headers)

    # ---- Security ----
    def create_security(self, payload, headers):
        return self._request("POST", "/securities", payload, headers)

    def update_quote(self, security_id, payload, headers):
        return self._request("PATCH", f"/securities/{security_id}/quote", payload, headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    def create_fill(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fills", payload, headers)

    def list_fills(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/fills", headers=headers, params=params)

    # ---- Settlement ----
    def list_settlements(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/settlements", headers=headers, params=params)

    def fail_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/fail", headers=headers)

    # ---- Position / Lot / Disposal ----
    def get_position(self, position_id, headers):
        return self._request("GET", f"/positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/positions", headers=headers, params=params)

    def set_drip(self, position_id, payload, headers):
        return self._request("PATCH", f"/positions/{position_id}/drip", payload, headers)

    def list_lots(self, position_id, headers, params=None):
        return self._request("GET", f"/positions/{position_id}/lots", headers=headers, params=params)

    def list_disposals(self, position_id, headers, params=None):
        return self._request("GET", f"/positions/{position_id}/disposals", headers=headers, params=params)

    # ---- Dividend ----
    def create_dividend(self, payload, headers):
        return self._request("POST", "/dividends", payload, headers)

    def list_dividends(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/dividends", headers=headers, params=params)

    def pay_dividend(self, dividend_id, headers):
        return self._request("POST", f"/dividends/{dividend_id}/pay", headers=headers)

    def reinvest_dividend(self, dividend_id, headers):
        return self._request("POST", f"/dividends/{dividend_id}/reinvest", headers=headers)

    def reverse_dividend(self, dividend_id, headers):
        return self._request("POST", f"/dividends/{dividend_id}/reverse", headers=headers)

    # ---- Options approval ----
    def create_options_approval(self, payload, headers):
        return self._request("POST", "/options-approvals", payload, headers)

    def list_options_approvals(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/options-approvals", headers=headers, params=params)

    def decide_options_approval(self, approval_id, payload, headers):
        return self._request("POST", f"/options-approvals/{approval_id}/decide", payload, headers)

    def revoke_options_approval(self, approval_id, headers):
        return self._request("POST", f"/options-approvals/{approval_id}/revoke", headers=headers)

    # ---- Margin calls ----
    def issue_margin_call(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/margin-calls", headers=headers)

    def list_margin_calls(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/margin-calls", headers=headers, params=params)

    def liquidate_margin_call(self, account_id, call_id, headers):
        return self._request("POST", f"/accounts/{account_id}/margin-calls/{call_id}/liquidate", headers=headers)

    # ---- Clock ----
    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
