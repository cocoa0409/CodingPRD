"""In-memory data store.

All state is held in plain dicts keyed by id. The store starts completely empty
on every boot — nothing is seeded, preloaded, or hardcoded.
"""

import uuid
from datetime import datetime, timezone, timedelta, date


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# Before any client advances it, the logical clock reads exactly
# 2026-08-01T00:00:00Z. The server MUST NOT fall back to real wall-clock time.
_LOGICAL_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_utc() -> datetime:
    """Return the current logical UTC instant."""
    return _LOGICAL_NOW


def current_logical_date() -> date:
    """Return the current logical calendar date."""
    return _LOGICAL_NOW.date()


def set_logical_now(new_now: datetime) -> None:
    global _LOGICAL_NOW
    _LOGICAL_NOW = new_now


def iso_timestamp(dt: datetime = None) -> str:
    """ISO 8601 UTC timestamp with three fractional digits (e.g. 2025-05-24T10:30:00.123Z)."""
    if dt is None:
        dt = now_utc()
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Entity tables — all start EMPTY
# ---------------------------------------------------------------------------
landlords = {}
properties = {}
units = {}
voucher_families = {}
payment_standards = {}
hap_contracts = {}
inspections = {}
repair_items = {}
rent_comparables = {}
rent_increase_requests = {}
recertifications = {}
hap_payments = {}
portability_actions = {}


def reset_all():
    """Clear every table. Only used by tests; never called on boot."""
    global _LOGICAL_NOW
    landlords.clear()
    properties.clear()
    units.clear()
    voucher_families.clear()
    payment_standards.clear()
    hap_contracts.clear()
    inspections.clear()
    repair_items.clear()
    rent_comparables.clear()
    rent_increase_requests.clear()
    recertifications.clear()
    hap_payments.clear()
    portability_actions.clear()
    _LOGICAL_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def touch(record: dict) -> None:
    """Refresh updated_at and bump version for a common-fields record."""
    record["updated_at"] = iso_timestamp()
    record["version"] = record.get("version", 1) + 1


def make_record(fields: dict, common: bool = True) -> dict:
    """Create a record dict with id/created_at/(updated_at, version)."""
    ts = iso_timestamp()
    rec = {"id": new_uuid(), "created_at": ts}
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    return rec
