"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- branches ---
    def create_branch(self, payload, headers):
        return self._request("POST", "/api/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/api/branches", params, headers)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/api/branches/{branch_id}", headers=headers)

    # --- tellers ---
    def create_teller(self, branch_id, payload, headers):
        return self._request("POST", f"/api/branches/{branch_id}/tellers", payload, headers)

    def list_tellers(self, headers, params=None):
        return self._request("GET", "/api/tellers", params, headers)

    def get_teller(self, teller_id, headers):
        return self._request("GET", f"/api/tellers/{teller_id}", headers=headers)

    def suspend_teller(self, teller_id, headers):
        return self._request("POST", f"/api/tellers/{teller_id}/suspend", {}, headers)

    def reinstate_teller(self, teller_id, headers):
        return self._request("POST", f"/api/tellers/{teller_id}/reinstate", {}, headers)

    # --- accounts ---
    def create_account(self, branch_id, payload, headers):
        return self._request("POST", f"/api/branches/{branch_id}/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", params, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/api/accounts/{account_id}/close", {}, headers)

    # --- drawers ---
    def open_drawer(self, teller_id, headers):
        return self._request("POST", f"/api/tellers/{teller_id}/drawers", {}, headers)

    def list_drawers(self, headers, params=None):
        return self._request("GET", "/api/drawers", params, headers)

    def get_drawer(self, drawer_id, headers):
        return self._request("GET", f"/api/drawers/{drawer_id}", headers=headers)

    def get_expected_cash(self, drawer_id, headers, variant=None):
        params = {"variant": variant} if variant else None
        return self._request("GET", f"/api/drawers/{drawer_id}/expected-cash", params, headers)

    def buy_from_vault(self, drawer_id, amount_cents, headers):
        return self._request("POST", f"/api/drawers/{drawer_id}/buy-from-vault",
                             {"amount_cents": amount_cents}, headers)

    def sell_to_vault(self, drawer_id, amount_cents, headers):
        return self._request("POST", f"/api/drawers/{drawer_id}/sell-to-vault",
                             {"amount_cents": amount_cents}, headers)

    def count_drawer(self, drawer_id, counted_cash_cents, headers):
        return self._request("POST", f"/api/drawers/{drawer_id}/count",
                             {"counted_cash_cents": counted_cash_cents}, headers)

    def attest_drawer(self, drawer_id, headers):
        return self._request("POST", f"/api/drawers/{drawer_id}/attest", {}, headers)

    def close_drawer(self, drawer_id, expected_drawer_version, headers):
        return self._request("POST", f"/api/drawers/{drawer_id}/close",
                             {"expected_drawer_version": expected_drawer_version}, headers)

    # --- transactions ---
    def post_transaction(self, drawer_id, payload, headers):
        return self._request("POST", f"/api/drawers/{drawer_id}/transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/api/transactions", params, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/api/transactions/{transaction_id}", headers=headers)

    def void_transaction(self, transaction_id, headers):
        return self._request("POST", f"/api/transactions/{transaction_id}/void", {}, headers)

    # --- cash orders ---
    def create_cash_order(self, branch_id, payload, headers):
        return self._request("POST", f"/api/branches/{branch_id}/cash-orders", payload, headers)

    def list_cash_orders(self, headers, params=None):
        return self._request("GET", "/api/cash-orders", params, headers)

    def get_cash_order(self, order_id, headers):
        return self._request("GET", f"/api/cash-orders/{order_id}", headers=headers)

    def get_cash_forecast(self, branch_id, delivery_date, headers):
        return self._request("GET", f"/api/branches/{branch_id}/cash-forecast",
                             {"delivery_date": delivery_date}, headers)

    def approve_cash_order(self, order_id, headers):
        return self._request("POST", f"/api/cash-orders/{order_id}/approve", {}, headers)

    def reject_cash_order(self, order_id, headers):
        return self._request("POST", f"/api/cash-orders/{order_id}/reject", {}, headers)

    def deliver_cash_order(self, order_id, headers):
        return self._request("POST", f"/api/cash-orders/{order_id}/deliver", {}, headers)

    def cancel_cash_order(self, order_id, headers):
        return self._request("POST", f"/api/cash-orders/{order_id}/cancel", {}, headers)

    # --- teller requests ---
    def create_teller_request(self, drawer_id, payload, headers):
        return self._request("POST", f"/api/drawers/{drawer_id}/teller-requests", payload, headers)

    def list_teller_requests(self, headers, params=None):
        return self._request("GET", "/api/teller-requests", params, headers)

    def get_teller_request(self, request_id, headers):
        return self._request("GET", f"/api/teller-requests/{request_id}", headers=headers)

    def approve_teller_request(self, request_id, headers):
        return self._request("POST", f"/api/teller-requests/{request_id}/approve", {}, headers)

    def reject_teller_request(self, request_id, headers):
        return self._request("POST", f"/api/teller-requests/{request_id}/reject", {}, headers)

    # --- holds ---
    def list_holds(self, headers, params=None):
        return self._request("GET", "/api/holds", params, headers)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/api/holds/{hold_id}", headers=headers)

    def waive_hold(self, hold_id, headers):
        return self._request("POST", f"/api/holds/{hold_id}/waive", {}, headers)

    # --- CTR filings ---
    def list_ctr_filings(self, headers, params=None):
        return self._request("GET", "/api/ctr-filings", params, headers)

    def get_ctr_filing(self, filing_id, headers):
        return self._request("GET", f"/api/ctr-filings/{filing_id}", headers=headers)

    # --- over/short cases ---
    def list_over_short_cases(self, headers, params=None):
        return self._request("GET", "/api/over-short-cases", params, headers)

    def get_over_short_case(self, case_id, headers):
        return self._request("GET", f"/api/over-short-cases/{case_id}", headers=headers)

    def investigate_case(self, case_id, headers):
        return self._request("POST", f"/api/over-short-cases/{case_id}/investigate", {}, headers)

    def resolve_case(self, case_id, headers):
        return self._request("POST", f"/api/over-short-cases/{case_id}/resolve", {}, headers)

    def waive_case(self, case_id, headers):
        return self._request("POST", f"/api/over-short-cases/{case_id}/waive", {}, headers)

    # --- approvals ---
    def list_approvals(self, headers, params=None):
        return self._request("GET", "/api/approvals", params, headers)

    def get_approval(self, approval_id, headers):
        return self._request("GET", f"/api/approvals/{approval_id}", headers=headers)

    # --- audits ---
    def create_audit(self, branch_id, payload, headers):
        return self._request("POST", f"/api/branches/{branch_id}/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/api/audits", params, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/api/audits/{audit_id}", headers=headers)

    def begin_audit(self, audit_id, headers):
        return self._request("POST", f"/api/audits/{audit_id}/begin", {}, headers)

    def complete_audit(self, audit_id, vault_counted_cents, drawer_counts, headers):
        return self._request("POST", f"/api/audits/{audit_id}/complete",
                             {"vault_counted_cents": vault_counted_cents,
                              "drawer_counts": drawer_counts}, headers)

    def cancel_audit(self, audit_id, headers):
        return self._request("POST", f"/api/audits/{audit_id}/cancel", {}, headers)


api_client = ApiClient()
