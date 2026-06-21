"""Record factories + serializers.

Common system fields (PRD §2.4): id (UUID, no prefix), created_at, updated_at
(ISO 8601 UTC, 3 fractional digits), version (int starting at 1, +1 every
mutation). Derived-field recomputes count as mutations, so any helper that
changes a record must call touch().

HipaaCertificate is the exception: only id + created_at, no updated_at/version
(it is immutable after issuance).
"""
from db import store
from timeutil import now_iso


def _common(record):
    """Stamp id + created_at/updated_at + version onto a fresh record."""
    rid = store.new_id()
    now = store.now()
    record["id"] = rid
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Mark a record mutated: bump updated_at to clock-now and increment
    version. Used for direct edits AND derived-field recomputes / cascades."""
    record["updated_at"] = store.now()
    record["version"] = record.get("version", 1) + 1
    return record


def _cert_common(record):
    record["id"] = store.new_id()
    record["created_at"] = store.now()
    record["_seq"] = store.next_seq()
    return record


# ---------------------------------------------------------------------------
# Datetime serialization: stored as aware datetimes internally; emitted as ISO.
# ---------------------------------------------------------------------------
_DATETIME_FIELDS = {
    "original_coverage_start", "event_date", "coverage_loss_date",
    "reported_at", "employer_notice_deadline", "notice_sent_date",
    "election_window_anchor", "election_deadline", "elected_at",
    "coverage_start_date", "scheduled_end_date", "actual_end_date",
    "initial_premium_due_date", "received_date", "paid_through_date",
    "coverage_from", "coverage_through",
}


def _serialize_value(key, value):
    if key in _DATETIME_FIELDS and value is not None:
        return now_iso(value)
    if key in ("created_at", "updated_at") and value is not None:
        return now_iso(value)
    return value


def serialize(record, fields):
    """Project a stored record into its public JSON shape, in the given field
    order, converting datetimes to ISO strings."""
    out = {}
    for f in fields:
        out[f] = _serialize_value(f, record.get(f))
    return out


# Public field orderings per entity (mirrors SCAFFOLD entity tables).
PLAN_FIELDS = [
    "id", "name", "applicable_premium_cents", "standard_admin_fee_pct",
    "disability_admin_fee_pct", "employer_notice_days", "election_notice_days",
    "election_window_days", "initial_premium_grace_days",
    "recurring_premium_grace_days", "insignificant_shortfall_floor_cents",
    "status", "created_at", "updated_at", "version",
]
BENEFICIARY_FIELDS = [
    "id", "plan_id", "full_name", "relationship", "original_coverage_start",
    "status", "created_at", "updated_at", "version",
]
EVENT_FIELDS = [
    "id", "plan_id", "beneficiary_id", "event_type", "event_date",
    "coverage_loss_date", "max_coverage_months", "reported_at",
    "employer_notice_deadline", "late_reported", "status",
    "created_at", "updated_at", "version",
]
NOTICE_FIELDS = [
    "id", "event_id", "beneficiary_id", "notice_sent_date",
    "election_window_anchor", "election_deadline", "status",
    "created_at", "updated_at", "version",
]
ENROLLMENT_FIELDS = [
    "id", "notice_id", "beneficiary_id", "event_id", "elected_at",
    "coverage_start_date", "base_max_months", "extension_months",
    "scheduled_end_date", "disability_extension", "actual_end_date",
    "termination_reason", "status", "created_at", "updated_at", "version",
]
ACCOUNT_FIELDS = [
    "id", "enrollment_id", "beneficiary_id", "monthly_premium_cents",
    "amount_invoiced_cents", "amount_paid_cents", "amount_subsidized_cents",
    "amount_refunded_cents", "credit_balance_cents", "paid_through_date",
    "initial_premium_due_date", "created_at", "updated_at", "version",
]
INVOICE_FIELDS = [
    "id", "account_id", "coverage_month", "coverage_month_index",
    "gross_premium_cents", "proration_mode", "amount_due_cents",
    "subsidy_applied_cents", "beneficiary_owed_cents", "status",
    "created_at", "updated_at", "version",
]
PAYMENT_FIELDS = [
    "id", "account_id", "amount_cents", "received_date",
    "target_coverage_month", "deemed_full_payment", "status",
    "created_at", "updated_at", "version",
]
SUBSIDY_FIELDS = [
    "id", "enrollment_id", "subsidy_pct", "start_month", "end_month",
    "status", "created_at", "updated_at", "version",
]
CERTIFICATE_FIELDS = [
    "id", "beneficiary_id", "enrollment_id", "coverage_from",
    "coverage_through", "creditable_months", "issued_reason", "created_at",
]
