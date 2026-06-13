"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the system-managed shape of a returned resource;
domain invariant checkers express cross-field guarantees stated in the PRD
(trial-balance equality, AR identity, balance-due identity).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

_ACCOUNT_TYPES = ["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_company(data: dict):
    _common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["accounting_basis"] in ("ACCRUAL", "CASH")
    assert data["trial_balance_status"] in ("BALANCED", "OUT_OF_BALANCE")
    assert isinstance(data["retained_earnings_cents"], int)


def assert_account(data: dict):
    _common(data)
    assert data["account_type"] in _ACCOUNT_TYPES, f"bad account_type {data.get('account_type')!r}"
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert isinstance(data["posted_balance_cents"], int)
    assert isinstance(data["is_cash"], bool)


def assert_accounting_period(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "CLOSING", "CLOSED")
    assert isinstance(data["close_checklist"], list)


def assert_journal_entry(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "POSTED", "VOIDED")
    assert data["source"] in ("MANUAL", "BANK_FEED", "CLOSING", "REVERSAL")
    assert isinstance(data["total_debit_cents"], int)
    assert isinstance(data["total_credit_cents"], int)


def assert_journal_line(data: dict):
    # Append-only immutable detail row: ONLY id + created_at (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "JournalLine must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "JournalLine must not carry version (PRD §2.4)"
    assert isinstance(data["debit_cents"], int) and data["debit_cents"] >= 0
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0


def assert_bank_account(data: dict):
    _common(data)
    assert isinstance(data["last_reconciled_statement_balance_cents"], int)


def assert_bank_feed_transaction(data: dict):
    _common(data)
    assert data["status"] in ("UNMATCHED", "CATEGORIZED", "EXCLUDED")
    assert isinstance(data["cleared"], bool)
    assert isinstance(data["amount_cents"], int)


def assert_reconciliation(data: dict):
    _common(data)
    assert data["status"] in ("IN_PROGRESS", "RECONCILED", "ABANDONED")
    assert isinstance(data["difference_cents"], int)


def assert_customer(data: dict):
    _common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0


def assert_invoice(data: dict):
    _common(data)
    assert data["delivery_status"] in ("DRAFT", "SENT", "VOID")
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID")
    for f in ("taxable_subtotal_cents", "nontaxable_subtotal_cents", "discount_cents",
              "tax_cents", "total_cents", "amount_paid_cents", "balance_due_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_invoice_payment(data: dict):
    _common(data)
    assert data["status"] in ("CLEARED", "REVERSED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_vendor(data: dict):
    _common(data)
    assert isinstance(data["is_1099_eligible"], bool)
    assert isinstance(data["ytd_1099_total_cents"], int)


def assert_bill(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "APPROVED", "PARTIALLY_PAID", "PAID", "VOID")
    for f in ("subtotal_cents", "use_tax_cents", "total_cents", "amount_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_tax_rate(data: dict):
    _common(data)
    assert isinstance(data["rate_bps"], int) and data["rate_bps"] >= 0


# --- Domain invariant checkers ---

def assert_invoice_ar_identity(invoice: dict):
    """PRD §3.7: amount_paid_cents + balance_due_cents == total_cents at all times."""
    assert invoice["amount_paid_cents"] + invoice["balance_due_cents"] == invoice["total_cents"], (
        f"AR identity violated: paid={invoice['amount_paid_cents']} "
        f"+ due={invoice['balance_due_cents']} != total={invoice['total_cents']}"
    )
