"""API client: one method per endpoint defined in the PRD.

Subclasses the framework GenericApiClient; the base _request() is inherited and
handles the response envelope. All paths are mounted under the /ledger prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Company ---
    def create_company(self, payload, headers):
        return self._request("POST", "/ledger/companies", payload, headers)

    def get_company(self, company_id, headers):
        return self._request("GET", f"/ledger/companies/{company_id}", headers=headers)

    def list_companies(self, headers, params=None):
        return self._request("GET", "/ledger/companies", headers=headers, params=params)

    def configure_company(self, company_id, payload, headers):
        return self._request("PATCH", f"/ledger/companies/{company_id}", payload, headers)

    def get_financial_statements(self, company_id, headers, params=None):
        return self._request(
            "GET", f"/ledger/companies/{company_id}/financial-statements",
            headers=headers, params=params,
        )

    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/ledger/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/ledger/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/ledger/accounts", headers=headers, params=params)

    def get_account_balance(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/ledger/accounts/{account_id}/balance", headers=headers, params=params,
        )

    def archive_account(self, account_id, headers):
        return self._request("POST", f"/ledger/accounts/{account_id}/archive", headers=headers)

    # --- AccountingPeriod ---
    def create_accounting_period(self, payload, headers):
        return self._request("POST", "/ledger/accounting-periods", payload, headers)

    def get_accounting_period(self, period_id, headers):
        return self._request("GET", f"/ledger/accounting-periods/{period_id}", headers=headers)

    def list_accounting_periods(self, headers, params=None):
        return self._request("GET", "/ledger/accounting-periods", headers=headers, params=params)

    def mark_checklist_item(self, period_id, payload, headers):
        return self._request(
            "POST", f"/ledger/accounting-periods/{period_id}/checklist", payload, headers,
        )

    def begin_close_period(self, period_id, headers):
        return self._request(
            "POST", f"/ledger/accounting-periods/{period_id}/begin-close", headers=headers,
        )

    def post_close_period(self, period_id, headers):
        return self._request(
            "POST", f"/ledger/accounting-periods/{period_id}/post-close", headers=headers,
        )

    def reopen_period(self, period_id, headers):
        return self._request(
            "POST", f"/ledger/accounting-periods/{period_id}/reopen", headers=headers,
        )

    # --- JournalEntry / JournalLine ---
    def create_journal_entry(self, payload, headers):
        return self._request("POST", "/ledger/journal-entries", payload, headers)

    def get_journal_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger/journal-entries/{entry_id}", headers=headers)

    def list_journal_entries(self, headers, params=None):
        return self._request("GET", "/ledger/journal-entries", headers=headers, params=params)

    def create_journal_line(self, payload, headers):
        return self._request("POST", "/ledger/journal-lines", payload, headers)

    def get_journal_line(self, line_id, headers):
        return self._request("GET", f"/ledger/journal-lines/{line_id}", headers=headers)

    def list_journal_lines(self, headers, params=None):
        return self._request("GET", "/ledger/journal-lines", headers=headers, params=params)

    def post_journal_entry(self, entry_id, headers):
        return self._request("POST", f"/ledger/journal-entries/{entry_id}/post", headers=headers)

    def void_journal_entry(self, entry_id, headers):
        return self._request("POST", f"/ledger/journal-entries/{entry_id}/void", headers=headers)

    # --- BankAccount ---
    def create_bank_account(self, payload, headers):
        return self._request("POST", "/ledger/bank-accounts", payload, headers)

    def get_bank_account(self, bank_account_id, headers):
        return self._request("GET", f"/ledger/bank-accounts/{bank_account_id}", headers=headers)

    def list_bank_accounts(self, headers, params=None):
        return self._request("GET", "/ledger/bank-accounts", headers=headers, params=params)

    # --- BankFeedTransaction ---
    def create_bank_feed_transaction(self, payload, headers):
        return self._request("POST", "/ledger/bank-feed-transactions", payload, headers)

    def get_bank_feed_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/ledger/bank-feed-transactions/{transaction_id}", headers=headers,
        )

    def list_bank_feed_transactions(self, headers, params=None):
        return self._request(
            "GET", "/ledger/bank-feed-transactions", headers=headers, params=params,
        )

    def categorize_transaction(self, transaction_id, payload, headers):
        return self._request(
            "POST", f"/ledger/bank-feed-transactions/{transaction_id}/categorize",
            payload, headers,
        )

    def recategorize_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"/ledger/bank-feed-transactions/{transaction_id}/recategorize",
            headers=headers,
        )

    def exclude_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"/ledger/bank-feed-transactions/{transaction_id}/exclude", headers=headers,
        )

    # --- Reconciliation ---
    def create_reconciliation(self, payload, headers):
        return self._request("POST", "/ledger/reconciliations", payload, headers)

    def get_reconciliation(self, reconciliation_id, headers):
        return self._request("GET", f"/ledger/reconciliations/{reconciliation_id}", headers=headers)

    def list_reconciliations(self, headers, params=None):
        return self._request("GET", "/ledger/reconciliations", headers=headers, params=params)

    def finalize_reconciliation(self, reconciliation_id, payload, headers):
        return self._request(
            "POST", f"/ledger/reconciliations/{reconciliation_id}/finalize", payload, headers,
        )

    def abandon_reconciliation(self, reconciliation_id, headers):
        return self._request(
            "POST", f"/ledger/reconciliations/{reconciliation_id}/abandon", headers=headers,
        )

    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/ledger/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/ledger/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/ledger/customers", headers=headers, params=params)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/ledger/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ledger/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/ledger/invoices", headers=headers, params=params)

    def send_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ledger/invoices/{invoice_id}/send", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ledger/invoices/{invoice_id}/void", headers=headers)

    # --- InvoicePayment ---
    def create_invoice_payment(self, payload, headers):
        return self._request("POST", "/ledger/invoice-payments", payload, headers)

    def get_invoice_payment(self, payment_id, headers):
        return self._request("GET", f"/ledger/invoice-payments/{payment_id}", headers=headers)

    def list_invoice_payments(self, headers, params=None):
        return self._request("GET", "/ledger/invoice-payments", headers=headers, params=params)

    def reverse_invoice_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/ledger/invoice-payments/{payment_id}/reverse", headers=headers,
        )

    # --- Vendor ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/ledger/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/ledger/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/ledger/vendors", headers=headers, params=params)

    def get_vendor_1099(self, vendor_id, headers):
        return self._request("GET", f"/ledger/vendors/{vendor_id}/1099", headers=headers)

    # --- Bill ---
    def create_bill(self, payload, headers):
        return self._request("POST", "/ledger/bills", payload, headers)

    def get_bill(self, bill_id, headers):
        return self._request("GET", f"/ledger/bills/{bill_id}", headers=headers)

    def list_bills(self, headers, params=None):
        return self._request("GET", "/ledger/bills", headers=headers, params=params)

    def approve_bill(self, bill_id, headers):
        return self._request("POST", f"/ledger/bills/{bill_id}/approve", headers=headers)

    def record_bill_payment(self, bill_id, payload, headers):
        return self._request("POST", f"/ledger/bills/{bill_id}/record-payment", payload, headers)

    def void_bill(self, bill_id, headers):
        return self._request("POST", f"/ledger/bills/{bill_id}/void", headers=headers)

    # --- TaxRate ---
    def create_tax_rate(self, payload, headers):
        return self._request("POST", "/ledger/tax-rates", payload, headers)

    def get_tax_rate(self, tax_rate_id, headers):
        return self._request("GET", f"/ledger/tax-rates/{tax_rate_id}", headers=headers)

    def list_tax_rates(self, headers, params=None):
        return self._request("GET", "/ledger/tax-rates", headers=headers, params=params)


api_client = ApiClient()
