"""Core shared services: timestamps/versioning, balance derivation, ledger
posting, program aggregation, pagination, request-body parsing, and the
round-half-up money helper. Every behavior here traces to a PRD sentence."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db, new_id, now_iso
from errors import err

# ---------------------------------------------------------------------------
# Money rounding (PRD §2.7): round-half-up to whole cents, used for the reload
# bonus, the escheat fraction, and the per-card B2B price only.
# ---------------------------------------------------------------------------


def round_half_up(value):
    """value: a numeric (cents * fraction) -> integer cents, round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# System-managed common fields (PRD §2.4).
# ---------------------------------------------------------------------------


def stamp_new(record, with_version=True):
    """Attach id/created_at[/updated_at/version] to a fresh record."""
    ts = now_iso(db.clock.now())
    record["id"] = new_id()
    record["created_at"] = ts
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation (PRD §2.9)."""
    record["updated_at"] = now_iso(db.clock.now())
    record["version"] = record.get("version", 1) + 1


def parse_iso(s):
    """Parse an ISO 8601 string to an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Request body parsing.
# ---------------------------------------------------------------------------


def get_body():
    if request.method in ("POST", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise err("ERR_VALIDATION", "Request body must be a JSON object.")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", f"Missing required field: {f}.")


def check_int(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {field}.")
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer.")
    return v


def check_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {field}.")
        return None
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"Field {field} must be a string.")
    return v


def check_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field {field} must be a boolean.")
    return v


def check_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {field}.")
        return None
    v = body[field]
    if v not in allowed:
        raise err("ERR_VALIDATION", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def check_number(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_VALIDATION", f"Missing required field: {field}.")
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"Field {field} must be a number.")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Sort by created_at ascending unless stated otherwise.
# ---------------------------------------------------------------------------


def paginate(items):
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)

    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None:
        lim = 10
    else:
        try:
            lim = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer.")
        if lim < 1:
            lim = 1
        elif lim > 100:
            lim = 100

    if offset is None:
        off = 0
    else:
        try:
            off = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be an integer.")
        if off < 0:
            off = 0

    page = items[off:off + lim]
    pagination = {
        "limit": lim,
        "offset": off,
        "total_count": total,
        "has_more": (off + lim) < total,
    }
    return page, pagination


# ---------------------------------------------------------------------------
# Balance derivation (PRD §2.5).
# ---------------------------------------------------------------------------


def settled_balance(card_id):
    """Sum amount_cents over POSTED ledger entries on this card."""
    return sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["card_id"] == card_id and e["status"] == "POSTED"
    )


def pending_hold(card_id):
    """Sum amount_cents over ACTIVE holds on this card."""
    return sum(
        h["amount_cents"]
        for h in db.holds.values()
        if h["card_id"] == card_id and h["status"] == "ACTIVE"
    )


def available_balance(card_id):
    return settled_balance(card_id) - pending_hold(card_id)


def last_activity_at(card):
    """created_at of the most recent POSTED LedgerEntry on this card, else the
    card's activation time (PRD §2.5)."""
    posted = [
        e for e in db.ledger_entries.values()
        if e["card_id"] == card["id"] and e["status"] == "POSTED"
    ]
    if posted:
        latest = max(posted, key=lambda e: (e["created_at"], e["id"]))
        return latest["created_at"]
    return card.get("activated_at")


# ---------------------------------------------------------------------------
# Ledger posting (append-only, PRD §2.4).
# ---------------------------------------------------------------------------


def post_ledger(card, entry_type, amount_cents, source_ref_id=None,
                reverses_entry_id=None):
    entry = {
        "card_id": card["id"],
        "program_id": card["program_id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "status": "POSTED",
        "source_ref_id": source_ref_id,
        "reverses_entry_id": reverses_entry_id,
    }
    stamp_new(entry, with_version=False)  # LedgerEntry: id + created_at only
    db.ledger_entries[entry["id"]] = entry
    return entry


# ---------------------------------------------------------------------------
# Program liability aggregation (PRD §2.6). These are computed on read; this
# helper exists so callers can be explicit that an op re-derives them, but the
# numbers are always re-summed from the ledger in the serializer.
# ---------------------------------------------------------------------------


def program_outstanding_liability(program_id):
    total = 0
    for c in db.cards.values():
        if c["program_id"] == program_id and c["lifecycle_status"] in ("ACTIVE", "EXHAUSTED"):
            total += settled_balance(c["id"])
    return total


def program_breakage_recognized(program_id):
    return sum(
        -e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["program_id"] == program_id and e["status"] == "POSTED"
        and e["entry_type"] == "BREAKAGE"
    )


def program_escheat_liability(program_id):
    return sum(
        -e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["program_id"] == program_id and e["status"] == "POSTED"
        and e["entry_type"] == "ESCHEAT"
    )
