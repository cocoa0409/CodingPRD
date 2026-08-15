"""Core record lifecycle, serializers, and shared domain queries.

Records store timestamps internally as aware datetimes; serializers render
ISO 8601 UTC strings with three fractional digits (PRD 2.5/2.8).
"""
from db import db, next_seq
from util import new_id, now, render_instant


def new_record(collection, fields, with_version=True):
    rec = dict(fields)
    rec["id"] = new_id()
    ts = now()
    rec["created_at"] = ts
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """PRD 2.5: updated_at refreshed and version incremented on every mutation,
    including cascade-driven ones."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1


def sort_key(rec):
    return (rec["created_at"], rec.get("_seq", 0))


# ---------------------------------------------------------------------------
# Ledger / computed fields
# ---------------------------------------------------------------------------

def scope_use_count(scope_id) -> int:
    """scope_use_ledger: count of ScopeUsage rows with status != VOID."""
    return sum(
        1 for u in db["scope_usages"].values()
        if u["scope_id"] == scope_id and u["status"] != "VOID"
    )


def scope_is_storage_current(scope) -> bool:
    """scope_storage_expiry: current while now is strictly before the expiry;
    a null expiry (never reprocessed) counts as current."""
    exp = scope.get("storage_expires_at")
    if exp is None:
        return True
    return now() < exp


def anesthesia_scheduled_minutes(anesthesia_provider_id) -> int:
    """anesthesia_minutes_ledger: sum of minutes over ASSIGNED/CONFIRMED rows."""
    return sum(
        a["minutes"]
        for a in db["anesthesia_assignments"].values()
        if a["anesthesia_provider_id"] == anesthesia_provider_id
        and a["status"] in ("ASSIGNED", "CONFIRMED")
    )


def active_usage_for_booking(booking_id):
    for u in db["scope_usages"].values():
        if u["booking_id"] == booking_id and u["status"] == "ACTIVE":
            return u
    return None


def open_quarantine_case_for_scope(scope_id):
    """The open (OPEN or RECULTURING) QuarantineCase for a scope, if any."""
    cases = [
        c for c in db["quarantine_cases"].values()
        if c["scope_id"] == scope_id and c["status"] in ("OPEN", "RECULTURING")
    ]
    if not cases:
        return None
    cases.sort(key=lambda c: c.get("_seq", 0))
    return cases[-1]


# ---------------------------------------------------------------------------
# Serializers (render datetimes; expose computed fields; strip internals)
# ---------------------------------------------------------------------------

_DATETIME_FIELDS = {
    "scheduled_start", "scheduled_end", "room_block_end", "actual_start",
    "actual_end", "storage_expires_at", "awaiting_reprocess_since",
    "used_at", "initiated_at", "precleaned_at", "cleaned_at", "disinfected_at",
    "dried_at", "completed_at", "sampled_at", "resulted_at", "opened_at",
    "resolved_at", "exposure_window_start", "exposure_window_end",
    "collected_at", "labeled_at", "handed_off_at", "received_at",
    "period_start", "period_end",
}


def _render_value(key, value):
    if value is None:
        return None
    if key in _DATETIME_FIELDS or key in ("created_at", "updated_at"):
        return render_instant(value)
    return value


def public(rec, computed=None):
    """Serialize a record: render timestamps, attach computed fields, strip _-keys."""
    if rec is None:
        return None
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        out[k] = _render_value(k, v)
    if computed:
        out.update(computed)
    return out


def public_scope(scope):
    return public(scope, computed={
        "use_count": scope_use_count(scope["id"]),
        "is_storage_current": scope_is_storage_current(scope),
    })


def public_anesthesia_provider(ap):
    return public(ap, computed={
        "scheduled_minutes": anesthesia_scheduled_minutes(ap["id"]),
    })


def public_for(collection, rec):
    if rec is None:
        return None
    if collection == "scopes":
        return public_scope(rec)
    if collection == "anesthesia_providers":
        return public_anesthesia_provider(rec)
    return public(rec)
