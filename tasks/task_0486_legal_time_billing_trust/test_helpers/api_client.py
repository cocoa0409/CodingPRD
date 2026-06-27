"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/firm/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/firm/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/firm/clients", headers=headers, params=params)

    def list_client_matters(self, client_id, headers, params=None):
        return self._request("GET", f"/firm/clients/{client_id}/matters", headers=headers, params=params)

    def get_client_ar_summary(self, client_id, headers):
        return self._request("GET", f"/firm/clients/{client_id}/ar-summary", headers=headers)

    def list_client_trust_ledgers(self, client_id, headers, params=None):
        return self._request("GET", f"/firm/clients/{client_id}/trust-ledgers", headers=headers, params=params)

    def list_client_conflict_checks(self, client_id, headers, params=None):
        return self._request("GET", f"/firm/clients/{client_id}/conflict-checks", headers=headers, params=params)

    def create_rate_override(self, client_id, payload, headers):
        return self._request("POST", f"/firm/clients/{client_id}/rate-overrides", payload, headers)

    def list_rate_overrides(self, client_id, headers, params=None):
        return self._request("GET", f"/firm/clients/{client_id}/rate-overrides", headers=headers, params=params)

    # ---- Timekeepers ----
    def create_timekeeper(self, payload, headers):
        return self._request("POST", "/firm/timekeepers", payload, headers)

    def get_timekeeper(self, timekeeper_id, headers):
        return self._request("GET", f"/firm/timekeepers/{timekeeper_id}", headers=headers)

    def list_timekeepers(self, headers, params=None):
        return self._request("GET", "/firm/timekeepers", headers=headers, params=params)

    # ---- Billing codes ----
    def create_billing_code(self, payload, headers):
        return self._request("POST", "/firm/billing-codes", payload, headers)

    def list_billing_codes(self, headers, params=None):
        return self._request("GET", "/firm/billing-codes", headers=headers, params=params)

    # ---- Matters ----
    def create_matter(self, payload, headers):
        return self._request("POST", "/firm/matters", payload, headers)

    def get_matter(self, matter_id, headers):
        return self._request("GET", f"/firm/matters/{matter_id}", headers=headers)

    def list_matters(self, headers, params=None):
        return self._request("GET", "/firm/matters", headers=headers, params=params)

    def get_matter_wip_summary(self, matter_id, headers):
        return self._request("GET", f"/firm/matters/{matter_id}/wip-summary", headers=headers)

    def create_conflict_check(self, matter_id, payload, headers):
        return self._request("POST", f"/firm/matters/{matter_id}/conflict-checks", payload, headers)

    def list_matter_conflict_checks(self, matter_id, headers, params=None):
        return self._request("GET", f"/firm/matters/{matter_id}/conflict-checks", headers=headers, params=params)

    def open_matter(self, matter_id, headers):
        return self._request("POST", f"/firm/matters/{matter_id}/open", {}, headers)

    def close_matter(self, matter_id, headers):
        return self._request("POST", f"/firm/matters/{matter_id}/close", {}, headers)

    # ---- Conflict checks ----
    def get_conflict_check(self, conflict_check_id, headers):
        return self._request("GET", f"/firm/conflict-checks/{conflict_check_id}", headers=headers)

    def waive_conflict_check(self, conflict_check_id, headers):
        return self._request("POST", f"/firm/conflict-checks/{conflict_check_id}/waive", {}, headers)

    # ---- Time / expense capture ----
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/firm/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/firm/time-entries/{time_entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/firm/time-entries", headers=headers, params=params)

    def write_down_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/firm/time-entries/{time_entry_id}/write-down", {}, headers)

    def create_expense_entry(self, payload, headers):
        return self._request("POST", "/firm/expense-entries", payload, headers)

    def get_expense_entry(self, expense_entry_id, headers):
        return self._request("GET", f"/firm/expense-entries/{expense_entry_id}", headers=headers)

    def list_expense_entries(self, headers, params=None):
        return self._request("GET", "/firm/expense-entries", headers=headers, params=params)

    # ---- Invoices ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/firm/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/firm/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/firm/invoices", headers=headers, params=params)

    def finalize_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/firm/invoices/{invoice_id}/finalize", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/firm/invoices/{invoice_id}/void", {}, headers)

    def create_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/firm/invoices/{invoice_id}/payments", payload, headers)

    def list_invoice_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/firm/invoices/{invoice_id}/payments", headers=headers, params=params)

    def trust_sweep(self, invoice_id, payload, headers):
        return self._request("POST", f"/firm/invoices/{invoice_id}/trust-sweep", payload, headers)

    def write_off_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/firm/invoices/{invoice_id}/write-off", payload, headers)

    def send_to_collections(self, invoice_id, headers):
        return self._request("POST", f"/firm/invoices/{invoice_id}/send-to-collections", {}, headers)

    # ---- Payments ----
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/firm/payments/{payment_id}", headers=headers)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/firm/payments/{payment_id}/reverse", {}, headers)

    # ---- Trust accounts ----
    def create_trust_account(self, payload, headers):
        return self._request("POST", "/firm/trust-accounts", payload, headers)

    def get_trust_account(self, trust_account_id, headers):
        return self._request("GET", f"/firm/trust-accounts/{trust_account_id}", headers=headers)

    def list_trust_account_ledgers(self, trust_account_id, headers, params=None):
        return self._request("GET", f"/firm/trust-accounts/{trust_account_id}/ledgers", headers=headers, params=params)

    def get_reconciliation(self, trust_account_id, headers):
        return self._request("GET", f"/firm/trust-accounts/{trust_account_id}/reconciliation", headers=headers)

    # ---- Trust ledgers ----
    def create_trust_ledger(self, payload, headers):
        return self._request("POST", "/firm/trust-ledgers", payload, headers)

    def get_trust_ledger(self, ledger_id, headers):
        return self._request("GET", f"/firm/trust-ledgers/{ledger_id}", headers=headers)

    def list_trust_ledgers(self, headers, params=None):
        return self._request("GET", "/firm/trust-ledgers", headers=headers, params=params)

    def list_ledger_transactions(self, ledger_id, headers, params=None):
        return self._request("GET", f"/firm/trust-ledgers/{ledger_id}/transactions", headers=headers, params=params)

    # ---- Trust transactions ----
    def create_trust_transaction(self, payload, headers):
        return self._request("POST", "/firm/trust-transactions", payload, headers)

    def get_trust_transaction(self, tx_id, headers):
        return self._request("GET", f"/firm/trust-transactions/{tx_id}", headers=headers)

    def list_trust_transactions(self, headers, params=None):
        return self._request("GET", "/firm/trust-transactions", headers=headers, params=params)

    def confirm_trust_transaction(self, tx_id, headers):
        return self._request("POST", f"/firm/trust-transactions/{tx_id}/confirm", {}, headers)

    def reverse_trust_transaction(self, tx_id, headers):
        return self._request("POST", f"/firm/trust-transactions/{tx_id}/reverse", {}, headers)

    # ---- Retainer holds ----
    def create_retainer_hold(self, payload, headers):
        return self._request("POST", "/firm/retainer-holds", payload, headers)

    def get_retainer_hold(self, hold_id, headers):
        return self._request("GET", f"/firm/retainer-holds/{hold_id}", headers=headers)

    def list_retainer_holds(self, headers, params=None):
        return self._request("GET", "/firm/retainer-holds", headers=headers, params=params)

    def release_retainer_hold(self, hold_id, headers):
        return self._request("POST", f"/firm/retainer-holds/{hold_id}/release", {}, headers)

    # ---- Logical clock / health ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def health(self, headers=None):
        return self._request("GET", "/firm/health", headers=headers)


api_client = ApiClient()
