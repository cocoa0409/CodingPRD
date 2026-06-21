"""Record factories + serializers (PRD §2.4).

Common system fields: id (UUID, no prefix), created_at, updated_at (ISO 8601 UTC,
3 fractional digits), version (int starting at 1, +1 every mutation). Derived-
field recomputes and cascade mutations count as mutations, so any helper that
changes a record must call touch().

ServiceCategory is the exception: it is immutable configuration carrying only id
and created_at (no updated_at, no version).
"""
from db import store
from timeutil import now_iso


def common(record):
    """Stamp id + created_at/updated_at + version onto a fresh full-quartet
    record."""
    record["id"] = store.new_id()
    now = store.now()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = store.next_seq()
    return record


def category_common(record):
    """ServiceCategory: only id + created_at (immutable config)."""
    record["id"] = store.new_id()
    record["created_at"] = store.now()
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Mark a record mutated: bump updated_at to clock-now and increment
    version. Used for direct edits AND derived-field recomputes / cascades."""
    record["updated_at"] = store.now()
    record["version"] = record.get("version", 1) + 1
    return record


# ---------------------------------------------------------------------------
# Datetime fields are stored internally as aware datetimes; emitted as ISO.
# ---------------------------------------------------------------------------
_DATETIME_FIELDS = {
    "created_at", "updated_at",
    "license_expires_on",
    "window_start", "window_end",
    "arrived_at",
}


def _serialize_value(key, value):
    if key in _DATETIME_FIELDS and value is not None:
        return now_iso(value)
    return value


def serialize(record, fields):
    """Project a stored record into its public JSON shape, in the given field
    order, converting datetimes to ISO strings."""
    out = {}
    for f in fields:
        out[f] = _serialize_value(f, record.get(f))
    return out


# Public field orderings per entity (mirrors SCAFFOLD §1.1 entity tables).
SERVICE_CATEGORY_FIELDS = [
    "id", "created_at", "code", "name", "requires_license", "pricing_model",
    "flat_task_fee_cents", "hourly_rate_cents", "instant_quote_eligible",
    "instant_quote_flat_cents", "callback_warranty_days", "skill_tags",
]
CUSTOMER_FIELDS = [
    "id", "email", "full_name", "zip_code", "wallet_credit_cents",
    "created_at", "updated_at", "version",
]
PRO_FIELDS = [
    "id", "email", "full_name", "home_zip_code", "skill_tags",
    "background_check_status", "license_status", "license_expires_on",
    "truck_stock_markup_pct", "completed_job_count", "callback_job_count",
    "callback_rate", "created_at", "updated_at", "version",
]
JOB_FIELDS = [
    "id", "customer_id", "category_id", "pro_id", "parent_job_id", "status",
    "quote_path", "agreed_price_cents", "is_warranty_callback",
    "address_zip_code", "created_at", "updated_at", "version",
]
QUOTE_FIELDS = [
    "id", "job_id", "quote_type", "estimated_labor_hours", "priced_amount_cents",
    "accepted", "superseded", "created_at", "updated_at", "version",
]
DISPATCH_WINDOW_FIELDS = [
    "id", "pro_id", "window_start", "window_end", "service_zip_code",
    "booked_job_id", "hold_state", "created_at", "updated_at", "version",
]
LABOR_LINE_FIELDS = [
    "id", "job_id", "hours_worked", "rate_cents_per_hour", "line_total_cents",
    "created_at", "updated_at", "version",
]
PART_LINE_FIELDS = [
    "id", "job_id", "description", "unit_cost_cents", "quantity",
    "from_truck_stock", "line_total_cents", "created_at", "updated_at", "version",
]
WORK_VISIT_FIELDS = [
    "id", "job_id", "dispatch_window_id", "arrived_at", "outcome",
    "created_at", "updated_at", "version",
]
INVOICE_FIELDS = [
    "id", "job_id", "labor_subtotal_cents", "parts_subtotal_cents",
    "trip_fee_cents", "total_cents", "amount_paid_cents", "refunded_cents",
    "balance_due_cents", "status", "created_at", "updated_at", "version",
]
DISPUTE_FIELDS = [
    "id", "job_id", "invoice_id", "reason", "requested_refund_cents",
    "refund_destination", "approved_refund_cents", "status",
    "created_at", "updated_at", "version",
]
BACKGROUND_CHECK_FIELDS = [
    "id", "pro_id", "check_type", "license_expires_on", "decision",
    "created_at", "updated_at", "version",
]
