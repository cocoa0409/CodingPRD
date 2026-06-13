"""Shared helpers: timestamp/version bookkeeping, datetime parsing, lookups,
list pagination, and validation primitives.
"""
from datetime import datetime, timezone

from db import db, new_id, now_iso, next_seq
from errors import ApiError


# ── System-field bookkeeping ────────────────────────────────────────────────

def stamp_new(record):
    """Attach common system fields for a full (versioned) entity."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def stamp_new_append_only(record):
    """Attach system fields for an append-only record (id + created_at only)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Mark a versioned entity as mutated: bump updated_at and version."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def touch_no_version(record):
    """Refresh updated_at without bumping version.

    Used for Recipe, whose `version` field is the revision counter (PRD 3.4),
    not a standard per-mutation OCC version — it only advances on revise.
    """
    record["updated_at"] = now_iso()
    return record


# ── Serialization (strip internal fields) ───────────────────────────────────

def public(record):
    """Return a copy without internal (underscore-prefixed) keys."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ── Datetime parsing ────────────────────────────────────────────────────────

def parse_dt(value):
    """Parse an ISO 8601 timestamp (with optional fractional seconds and a Z or
    offset) into an aware UTC datetime. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── Lookups ─────────────────────────────────────────────────────────────────

def get_or_404(collection, entity_id):
    rec = collection.get(entity_id)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


def find_member(member_id):
    return get_or_404(db.members, member_id)


# ── List helpers ────────────────────────────────────────────────────────────

def sorted_by_creation(records):
    """Ascending creation order using the monotonic insertion sequence."""
    return sorted(records, key=lambda r: r["_seq"])


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return [public(r) for r in page], total


# ── Body validation primitives ──────────────────────────────────────────────

def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError("ERR_INVALID_REQUEST")


def as_int(value):
    """Coerce to int only when the value is genuinely integral (no bools)."""
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ApiError("ERR_INVALID_REQUEST")


def as_number(value):
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST")
    if isinstance(value, (int, float)):
        return value
    raise ApiError("ERR_INVALID_REQUEST")
