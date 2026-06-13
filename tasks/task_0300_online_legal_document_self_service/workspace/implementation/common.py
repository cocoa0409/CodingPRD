"""Shared helpers: entity scaffolding, serialization, listing, datetime parsing,
and money rounding."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import new_id, now_iso, store


# --------------------------------------------------------------------------
# Money rounding (PRD §2.7: round-half-up to whole cents).
# --------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a numeric (cents, possibly fractional) to a whole-cent int using
    round-half-up. Accepts int/float/Decimal."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_discount_cents(line_cents, discount_pct):
    """line * (1 - discount), round_half_up to whole cents. discount_pct is a
    fraction 0.0..1.0."""
    factor = Decimal("1") - Decimal(str(discount_pct))
    return round_half_up_cents(Decimal(str(line_cents)) * factor)


# --------------------------------------------------------------------------
# Common system fields.
# --------------------------------------------------------------------------
def base_entity(with_version=True):
    """Create id/created_at and (optionally) updated_at/version. A monotonic
    sequence is stored under _seq for deterministic created_at-ASC ordering."""
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "_seq": store.next_seq(),
    }
    if with_version:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def touch(ent):
    """Record a mutation: bump updated_at and version (audit fields, PRD §2.5).
    Cascaded mutations call this too — server-initiated changes are recorded
    exactly like client ones."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 1) + 1


# --------------------------------------------------------------------------
# Serialization: strip internal keys (those beginning with "_").
# --------------------------------------------------------------------------
def serialize(ent):
    if ent is None:
        return None
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# --------------------------------------------------------------------------
# Listing: filter, sort by created_at ASC (via _seq), paginate.
# --------------------------------------------------------------------------
def list_collection(collection, predicate, limit, offset):
    """Return (page_items_serialized, total_count). Sorted created_at ASC by
    the monotonic creation sequence."""
    items = [e for e in collection.values() if predicate(e)]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return [serialize(e) for e in page], total


# --------------------------------------------------------------------------
# Datetime parsing (UTC, ISO 8601 — lease windows and review windows).
# --------------------------------------------------------------------------
def parse_datetime(value, field_name="datetime"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime. Raises
    ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field_name} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"{field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Lookup helpers (existence -> ERR_NOT_FOUND).
# --------------------------------------------------------------------------
def get_or_404(collection, ent_id):
    ent = collection.get(ent_id)
    if ent is None:
        raise errors.not_found()
    return ent
