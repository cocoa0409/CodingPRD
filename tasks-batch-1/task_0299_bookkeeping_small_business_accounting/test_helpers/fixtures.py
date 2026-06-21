"""Composite setup helpers.

Most interesting claims require the ledger to be in a multi-step state: a company
with a chart of accounts and an OPEN period, posted entries, sent invoices,
approved bills, categorized bank transactions, or a closed period. These helpers
encapsulate those preambles so individual tests focus on the behavior under test.

Every helper builds its preconditions from scratch via PRD-declared endpoints (the
test harness restarts the server with an empty database before each test). Setup
calls use get_success_data() so a setup failure surfaces as a clear "Setup failed".

Identity threading: a journal entry is drafted under the Bookkeeper id u_book and
posted under the Accountant id u_acct, so the maker-checker rule (PRD §3.4) is
satisfied — the poster's X-User-ID differs from the drafter's created_by_user_id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client as api
from .test_users import (
    make_owner_headers, make_accountant_headers, make_bookkeeper_headers,
)
from . import factories as F

# Distinct opaque ids so maker (drafter) != checker (poster).
OWNER = make_owner_headers("u_owner")
ACCT = make_accountant_headers("u_acct")
BOOK = make_bookkeeper_headers("u_book")

STD_START = "2026-01-01T00:00:00.000Z"
STD_END = "2026-02-01T00:00:00.000Z"


def _data(resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: Company + chart of accounts + OPEN period
# ---------------------------------------------------------------------------

def setup_company_with_accounts(accounting_basis="ACCRUAL", account_specs=None,
                                open_period=True, with_bank=False):
    """Create a Company, a chart of accounts, configure retained earnings, and
    (by default) open a contiguous first period.

    account_specs: list of (key, code, name, account_type, is_cash) tuples.
    Defaults to a full Cash/AR/AP/Revenue/Expense/TaxLiab/RetainedEarnings chart.
    Returns a dict with: company, company_version (current), period (or None),
    accounts {key: account_dict}, bank (or None).
    """
    if account_specs is None:
        account_specs = [
            ("cash", "1000", "Cash", "ASSET", True),
            ("ar", "1100", "Accounts Receivable", "ASSET", False),
            ("ap", "2000", "Accounts Payable", "LIABILITY", False),
            ("taxliab", "2200", "Sales Tax Payable", "LIABILITY", False),
            ("rev", "4000", "Revenue", "REVENUE", False),
            ("exp", "6000", "Expense", "EXPENSE", False),
            ("re", "3900", "Retained Earnings", "EQUITY", False),
        ]

    company = _data(api.create_company(
        F.create_company_payload(accounting_basis=accounting_basis), OWNER))
    co = company["id"]
    co_v = company["version"]

    accounts = {}
    for key, code, name, atype, is_cash in account_specs:
        acct = _data(api.create_account(
            F.create_account_payload(co, code, name, atype, is_cash=is_cash), OWNER))
        accounts[key] = acct

    re_id = accounts["re"]["id"] if "re" in accounts else None
    if re_id is not None:
        company = _data(api.configure_company(
            co, F.configure_company_payload(re_id, co_v), OWNER))
        co_v = company["version"]

    bank = None
    if with_bank:
        bank = _data(api.create_bank_account(
            F.create_bank_account_payload(co, accounts["cash"]["id"]), OWNER))

    period = None
    if open_period:
        period = _data(api.create_accounting_period(
            F.create_accounting_period_payload(co, co_v), OWNER))
        company = _data(api.get_company(co, OWNER))
        co_v = company["version"]

    return {
        "company": company,
        "company_version": co_v,
        "period": period,
        "accounts": accounts,
        "bank": bank,
    }


# ---------------------------------------------------------------------------
# Tier 1 / Tier 3: Journal entries
# ---------------------------------------------------------------------------

def create_draft_entry_with_lines(company_id, period_id, lines, entry_date="2026-01-10T00:00:00.000Z",
                                  memo="entry"):
    """Create a DRAFT journal entry (drafted by u_book) and attach lines.

    lines: list of (account_id, debit_cents, credit_cents) tuples.
    Returns the entry dict (as created; totals reflect the added lines on re-fetch).
    """
    entry = _data(api.create_journal_entry(
        F.create_journal_entry_payload(company_id, period_id, entry_date, memo=memo), BOOK))
    for account_id, debit, credit in lines:
        extra = {}
        if debit:
            extra["debit_cents"] = debit
        if credit:
            extra["credit_cents"] = credit
        _data(api.create_journal_line(
            F.create_journal_line_payload(entry["id"], account_id, **extra), BOOK))
    return _data(api.get_journal_entry(entry["id"], BOOK))


def create_posted_entry(company_id, period_id, lines, entry_date="2026-01-10T00:00:00.000Z",
                        memo="posted"):
    """Create a balanced DRAFT entry (drafter u_book), then post it (poster u_acct).
    Returns the POSTED entry dict."""
    entry = create_draft_entry_with_lines(company_id, period_id, lines, entry_date, memo)
    return _data(api.post_journal_entry(entry["id"], ACCT))


# ---------------------------------------------------------------------------
# Tier 3: Bank-feed categorization
# ---------------------------------------------------------------------------

def import_transaction(company_id, bank_account_id, amount_cents,
                       posted_date="2026-01-10T00:00:00.000Z", description="LINE"):
    """Import one UNMATCHED bank-feed transaction. Returns the transaction dict."""
    return _data(api.create_bank_feed_transaction(
        F.create_bank_feed_transaction_payload(
            company_id, bank_account_id, amount_cents,
            posted_date=posted_date, bank_description=description), BOOK))


def import_and_categorize(company_id, bank_account_id, amount_cents, counter_account_id,
                          posted_date="2026-01-10T00:00:00.000Z", description="LINE"):
    """Import a transaction then categorize it (-> CATEGORIZED). Returns the txn dict."""
    txn = import_transaction(company_id, bank_account_id, amount_cents, posted_date, description)
    return _data(api.categorize_transaction(
        txn["id"], F.categorize_payload(counter_account_id), BOOK))


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3: Customers and invoices
# ---------------------------------------------------------------------------

def create_customer(company_id, ar_account_id, tax_jurisdiction="NONE", display_name="Buyer"):
    return _data(api.create_customer(
        F.create_customer_payload(company_id, ar_account_id,
                                  tax_jurisdiction=tax_jurisdiction,
                                  display_name=display_name), BOOK))


def create_draft_invoice(company_id, customer_id, revenue_account_id, tax_liability_account_id,
                         lines, issue_date="2026-01-15T00:00:00.000Z"):
    return _data(api.create_invoice(
        F.create_invoice_payload(company_id, customer_id, revenue_account_id,
                                 tax_liability_account_id, lines, issue_date=issue_date), BOOK))


def create_sent_invoice(company_id, customer_id, revenue_account_id, tax_liability_account_id,
                        lines, issue_date="2026-01-15T00:00:00.000Z"):
    """Create a DRAFT invoice (drafter u_book) and send it (sender u_acct).
    Returns the SENT invoice dict."""
    inv = create_draft_invoice(company_id, customer_id, revenue_account_id,
                               tax_liability_account_id, lines, issue_date)
    return _data(api.send_invoice(inv["id"], ACCT))


def setup_sent_invoice(unit_price_cents=100000, taxable=False, tax_jurisdiction="NONE",
                       rate_bps=None):
    """Full chain to a SENT invoice with one line, plus a BankAccount for payments.
    Returns a dict: env (from setup_company_with_accounts), customer, invoice."""
    env = setup_company_with_accounts(with_bank=True)
    co = env["company"]["id"]
    accts = env["accounts"]
    if rate_bps is not None:
        _data(api.create_tax_rate(
            F.create_tax_rate_payload(co, tax_jurisdiction, rate_bps), ACCT))
    cust = create_customer(co, accts["ar"]["id"], tax_jurisdiction=tax_jurisdiction)
    lines = [{"description": "svc", "quantity": 1,
              "unit_price_cents": unit_price_cents, "taxable": taxable}]
    inv = create_sent_invoice(co, cust["id"], accts["rev"]["id"],
                              accts["taxliab"]["id"], lines)
    return {"env": env, "customer": cust, "invoice": inv}


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3: Vendors and bills
# ---------------------------------------------------------------------------

def create_vendor(company_id, ap_account_id, is_1099_eligible=False, display_name="Vendor"):
    return _data(api.create_vendor(
        F.create_vendor_payload(company_id, ap_account_id,
                                is_1099_eligible=is_1099_eligible,
                                display_name=display_name), ACCT))


def create_draft_bill(company_id, vendor_id, expense_account_id, lines,
                      bill_date="2026-01-08T00:00:00.000Z"):
    return _data(api.create_bill(
        F.create_bill_payload(company_id, vendor_id, expense_account_id, lines,
                              bill_date=bill_date), BOOK))


def create_approved_bill(company_id, vendor_id, expense_account_id, lines,
                         bill_date="2026-01-08T00:00:00.000Z"):
    bill = create_draft_bill(company_id, vendor_id, expense_account_id, lines, bill_date)
    return _data(api.approve_bill(bill["id"], ACCT))


# ---------------------------------------------------------------------------
# Tier 5: Period close progression
# ---------------------------------------------------------------------------

def complete_checklist(period_id):
    """Mark all four close-checklist items done."""
    for item in ("BANK_RECONCILED", "AR_REVIEWED", "AP_REVIEWED", "SALES_TAX_REVIEWED"):
        _data(api.mark_checklist_item(period_id, F.checklist_item_payload(item, True), ACCT))


def begin_close(period_id):
    return _data(api.begin_close_period(period_id, ACCT))


def setup_period_in_closing(env):
    """Take an env with an OPEN period to CLOSING (all checklist items done).
    Assumes no DRAFT entries and no IN_PROGRESS reconciliation. Returns the period."""
    period_id = env["period"]["id"]
    complete_checklist(period_id)
    return begin_close(period_id)


def setup_closed_period_with_revenue(revenue_cents=100000):
    """Full chain to a CLOSED period: post one revenue sale, complete the checklist,
    begin-close, post-close. Returns a dict with env, period (CLOSED), and the
    closing journal entry id."""
    env = setup_company_with_accounts()
    co = env["company"]["id"]
    accts = env["accounts"]
    period_id = env["period"]["id"]
    create_posted_entry(co, period_id,
                        [(accts["ar"]["id"], revenue_cents, 0),
                         (accts["rev"]["id"], 0, revenue_cents)],
                        memo="sale")
    complete_checklist(period_id)
    begin_close(period_id)
    period = _data(api.post_close_period(period_id, ACCT))
    return {
        "env": env,
        "period": period,
        "closing_journal_entry_id": period.get("closing_journal_entry_id"),
    }


# ---------------------------------------------------------------------------
# Tier 3: Reconciliation
# ---------------------------------------------------------------------------

def setup_reconciliation(opening, ending, included_transaction_ids, company_id, bank_account_id):
    """Create an IN_PROGRESS reconciliation. Returns the reconciliation dict."""
    return _data(api.create_reconciliation(
        F.create_reconciliation_payload(company_id, bank_account_id, opening, ending,
                                        included_transaction_ids), ACCT))
