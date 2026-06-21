"""Payload factories — one per entity, input fields only.

Every factory yields a minimal valid creation body; tests pass **overrides for
the fields they need to control.
"""
from .constants import PERIOD_START, PERIOD_END


def create_company_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Company",
        "base_currency": "USD",
        "accounting_basis": "ACCRUAL",
    }
    defaults.update(overrides)
    return defaults


def configure_company_payload(retained_earnings_account_id, expected_company_version, **overrides) -> dict:
    defaults = {
        "retained_earnings_account_id": retained_earnings_account_id,
        "expected_company_version": expected_company_version,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(company_id, code, name, account_type, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "code": code,
        "name": name,
        "account_type": account_type,
    }
    defaults.update(overrides)
    return defaults


def create_accounting_period_payload(company_id, expected_company_version, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "period_label": "2026-01",
        "start_date": PERIOD_START,
        "end_date": PERIOD_END,
        "expected_company_version": expected_company_version,
    }
    defaults.update(overrides)
    return defaults


def checklist_item_payload(item, done=True, **overrides) -> dict:
    defaults = {"item": item, "done": done}
    defaults.update(overrides)
    return defaults


def create_journal_entry_payload(company_id, period_id, entry_date, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "period_id": period_id,
        "entry_date": entry_date,
    }
    defaults.update(overrides)
    return defaults


def create_journal_line_payload(journal_entry_id, account_id, **overrides) -> dict:
    defaults = {
        "journal_entry_id": journal_entry_id,
        "account_id": account_id,
    }
    defaults.update(overrides)
    return defaults


def create_bank_account_payload(company_id, gl_account_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "gl_account_id": gl_account_id,
        "nickname": "Checking",
    }
    defaults.update(overrides)
    return defaults


def create_bank_feed_transaction_payload(company_id, bank_account_id, amount_cents, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "bank_account_id": bank_account_id,
        "posted_date": "2026-01-10T00:00:00.000Z",
        "amount_cents": amount_cents,
        "bank_description": "BANK LINE",
    }
    defaults.update(overrides)
    return defaults


def categorize_payload(counter_account_id, **overrides) -> dict:
    defaults = {"counter_account_id": counter_account_id}
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(company_id, bank_account_id, statement_opening_balance_cents,
                                  statement_ending_balance_cents, included_transaction_ids,
                                  **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "bank_account_id": bank_account_id,
        "statement_start_date": PERIOD_START,
        "statement_end_date": PERIOD_END,
        "statement_opening_balance_cents": statement_opening_balance_cents,
        "statement_ending_balance_cents": statement_ending_balance_cents,
        "included_transaction_ids": included_transaction_ids,
    }
    defaults.update(overrides)
    return defaults


def finalize_reconciliation_payload(expected_bank_account_version, **overrides) -> dict:
    defaults = {"expected_bank_account_version": expected_bank_account_version}
    defaults.update(overrides)
    return defaults


def create_customer_payload(company_id, ar_account_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "display_name": "Test Customer",
        "tax_jurisdiction": "NONE",
        "ar_account_id": ar_account_id,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(company_id, customer_id, revenue_account_id, tax_liability_account_id,
                           lines, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "customer_id": customer_id,
        "revenue_account_id": revenue_account_id,
        "tax_liability_account_id": tax_liability_account_id,
        "issue_date": "2026-01-15T00:00:00.000Z",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payment_payload(company_id, invoice_id, deposit_bank_account_id,
                                   amount_cents, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "invoice_id": invoice_id,
        "deposit_bank_account_id": deposit_bank_account_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(company_id, ap_account_id, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "display_name": "Test Vendor",
        "ap_account_id": ap_account_id,
        "is_1099_eligible": False,
    }
    defaults.update(overrides)
    return defaults


def create_bill_payload(company_id, vendor_id, expense_account_id, lines, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "vendor_id": vendor_id,
        "expense_account_id": expense_account_id,
        "bill_date": "2026-01-08T00:00:00.000Z",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def record_bill_payment_payload(pay_from_bank_account_id, amount_cents, **overrides) -> dict:
    defaults = {
        "pay_from_bank_account_id": pay_from_bank_account_id,
        "amount_cents": amount_cents,
        "payment_date": "2026-01-20T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_tax_rate_payload(company_id, jurisdiction, rate_bps, **overrides) -> dict:
    defaults = {
        "company_id": company_id,
        "jurisdiction": jurisdiction,
        "rate_bps": rate_bps,
        "effective_from": "2026-01-01T00:00:00.000Z",
        "effective_to": "2027-01-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults
