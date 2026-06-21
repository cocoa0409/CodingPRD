"""Shared helpers: common-field stamping, validation, date math, pagination.

PRD §2.4: most resources carry id/created_at/updated_at/version. DamageCharge,
AccountLedgerEntry, and YardClock carry only id/created_at (no updated_at, no
version).
"""
import copy
from datetime import date, datetime, timezone

import errors
from db import DB, new_id, now_iso


# --------------------------------------------------------------------------
# Common-field lifecycle
# --------------------------------------------------------------------------

def new_record(extra_fields, full_common=True):
    """Build a new record with system common fields.

    full_common True  -> id/created_at/updated_at/version (version starts at 1).
    full_common False -> id/created_at only (append-only/singleton entities).
    """
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts}
    if full_common:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = DB.next_seq()
    rec.update(extra_fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version by one on a mutation (PRD §2.4).

    Only applies to records that carry these fields.
    """
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()


def serialize(rec):
    """Strip internal-only fields for the API response."""
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    return out


# --------------------------------------------------------------------------
# Field validation helpers (ERR_INVALID_REQUEST, PRD §3.x)
# --------------------------------------------------------------------------

def require_body(body):
    if body is None or not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def req_str(body, field, min_len=1, max_len=None):
    val = body.get(field)
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be a string.")
    if len(val) < min_len:
        raise errors.invalid_request(f"Field '{field}' is too short.")
    if max_len is not None and len(val) > max_len:
        raise errors.invalid_request(f"Field '{field}' is too long.")
    return val


def req_int(body, field, minimum=None):
    val = body.get(field)
    # bool is a subclass of int; reject it as a non-integer for numeric fields.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}.")
    return val


def req_number(body, field, minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}.")
    return val


def opt_bool(body, field, default=False):
    val = body.get(field, default)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field '{field}' must be a boolean.")
    return val


def req_enum(body, field, members):
    val = body.get(field)
    if not isinstance(val, str) or val not in members:
        raise errors.invalid_request(
            f"Field '{field}' must be one of {sorted(members)}.")
    return val


def req_date(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be a YYYY-MM-DD date string.")
    try:
        parse_date(val)
    except ValueError:
        raise errors.invalid_request(f"Field '{field}' must be a valid YYYY-MM-DD date.")
    return val


def req_datetime(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be an ISO 8601 datetime string.")
    try:
        parse_datetime(val)
    except ValueError:
        raise errors.invalid_request(f"Field '{field}' must be a valid ISO 8601 datetime.")
    return val


# --------------------------------------------------------------------------
# Date / datetime parsing & math
# --------------------------------------------------------------------------

def parse_date(s):
    """Parse a YYYY-MM-DD date-only string into a date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def parse_datetime(s):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC)."""
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def billed_days(start_str, end_str):
    """Inclusive day count over [start, end]: (end - start).days + 1 (PRD §3.4)."""
    s = parse_date(start_str)
    e = parse_date(end_str)
    return (e - s).days + 1


def clock_date_str():
    """Date portion (YYYY-MM-DD) of the yard clock current_utc (PRD §2.7)."""
    from db import ensure_clock
    clk = ensure_clock()
    dt = parse_datetime(clk["current_utc"])
    return dt.date().isoformat()


# --------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND, PRD §2.5 — left to right)
# --------------------------------------------------------------------------

def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


# --------------------------------------------------------------------------
# Pagination application (PRD §2.3 — sort by created_at ASC unless noted)
# --------------------------------------------------------------------------

def sort_by_created(records):
    """Sort by created_at ASC, tie-broken by insertion sequence (PRD §2.3)."""
    return sorted(records, key=lambda r: (r.get("created_at"), r.get("_seq", 0)))


def paginate(records, limit, offset):
    """Apply offset/limit window after the caller has sorted. Returns (page, total)."""
    total = len(records)
    page = records[offset:offset + limit]
    return page, total
