"""Entity -> public JSON projections. Internal fields (e.g. _seq) are dropped."""

from common import public

CLIENT_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "display_name", "client_type", "status", "ar_balance_cents",
]

TIMEKEEPER_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "full_name", "role_kind", "standard_rate_cents", "is_active",
]

MATTER_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "client_id", "responsible_timekeeper_id", "title", "matter_rate_cents",
    "status", "wip_fees_cents", "wip_expenses_cents",
]

CONFLICT_CHECK_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "matter_id", "adverse_party_client_id", "adverse_party_name",
    "result", "matched_client_id", "approved_by_user_id",
]

TIME_ENTRY_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "matter_id", "timekeeper_id", "worked_at", "minutes",
    "utbms_task_code", "utbms_activity_code",
    "resolved_rate_cents", "billable_amount_cents", "status", "invoice_id",
]

EXPENSE_ENTRY_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "matter_id", "utbms_expense_code", "amount_cents", "status", "invoice_id",
]

BILLING_CODE_FIELDS = [
    "id", "created_at", "code", "kind", "label",
]

INVOICE_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "matter_id", "client_id", "issue_date", "net_terms_days",
    "fees_subtotal_cents", "expenses_subtotal_cents", "written_off_cents",
    "total_cents", "amount_paid_cents", "billing_status", "collection_status",
]

TRUST_ACCOUNT_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "name", "book_balance_cents", "bank_balance_cents",
]

CLIENT_TRUST_LEDGER_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "trust_account_id", "client_id", "balance_cents", "retainer_floor_cents",
]

RETAINER_HOLD_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "client_trust_ledger_id", "amount_cents", "hold_start_at", "hold_end_at",
    "status",
]

TRUST_TRANSACTION_FIELDS = [
    "id", "created_at",
    "client_trust_ledger_id", "kind", "amount_cents", "status",
    "invoice_id", "initiated_by_user_id", "approved_by_user_id",
]

PAYMENT_FIELDS = [
    "id", "created_at", "updated_at", "version",
    "invoice_id", "amount_cents", "method", "status",
]

RATE_OVERRIDE_FIELDS = [
    "id", "client_id", "role_kind", "rate_cents",
]


def s_client(r):
    return public(r, CLIENT_FIELDS)


def s_timekeeper(r):
    return public(r, TIMEKEEPER_FIELDS)


def s_matter(r):
    return public(r, MATTER_FIELDS)


def s_conflict_check(r):
    return public(r, CONFLICT_CHECK_FIELDS)


def s_time_entry(r):
    return public(r, TIME_ENTRY_FIELDS)


def s_expense_entry(r):
    return public(r, EXPENSE_ENTRY_FIELDS)


def s_billing_code(r):
    return public(r, BILLING_CODE_FIELDS)


def s_invoice(r):
    return public(r, INVOICE_FIELDS)


def s_trust_account(r):
    return public(r, TRUST_ACCOUNT_FIELDS)


def s_trust_ledger(r):
    return public(r, CLIENT_TRUST_LEDGER_FIELDS)


def s_retainer_hold(r):
    return public(r, RETAINER_HOLD_FIELDS)


def s_trust_transaction(r):
    return public(r, TRUST_TRANSACTION_FIELDS)


def s_payment(r):
    return public(r, PAYMENT_FIELDS)


def s_rate_override(r):
    return public(r, RATE_OVERRIDE_FIELDS)
