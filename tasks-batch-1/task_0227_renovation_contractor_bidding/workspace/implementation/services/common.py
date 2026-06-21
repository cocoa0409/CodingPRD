"""Shared helpers: entity stamping, rounding, pagination, parsing."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors


# ---------------------------------------------------------------------------
# Common-field stamping (PRD §2.4): id, created_at, updated_at, version
# ---------------------------------------------------------------------------
def stamp_new(record):
    """Populate server-minted common fields on a freshly created record."""
    now = db.iso_now()
    record["id"] = db.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    # monotonic creation counter used for stable created_at-ascending ordering
    record["_seq"] = _next_seq()
    return record


_seq_counter = {"n": 0}


def _next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def touch(record):
    """Mark a record mutated: refresh updated_at, bump version."""
    record["updated_at"] = db.iso_now()
    record["version"] = record.get("version", 0) + 1
    return record


# ---------------------------------------------------------------------------
# Rounding (PRD §2.5): round-half-up
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest integer, half away from zero (up)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dp(value, dp):
    """Round to `dp` decimal places half-up; returns a float."""
    q = Decimal("1") if dp == 0 else Decimal("1").scaleb(-dp)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Public view: drop private bookkeeping fields
# ---------------------------------------------------------------------------
def public(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (via _seq), then apply limit/offset.

    Returns (page_items_public, limit, offset, total_count).
    """
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Body parsing & field validation
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}.")
    return body[name]


def as_int(value, name):
    if isinstance(value, bool):
        raise errors.invalid_request(f"{name} must be an integer.")
    if isinstance(value, int):
        return value
    raise errors.invalid_request(f"{name} must be an integer.")


def as_number(value, name):
    if isinstance(value, bool):
        raise errors.invalid_request(f"{name} must be a number.")
    if isinstance(value, (int, float)):
        return value
    raise errors.invalid_request(f"{name} must be a number.")


def as_str(value, name):
    if not isinstance(value, str):
        raise errors.invalid_request(f"{name} must be a string.")
    return value


def as_enum(value, name, allowed):
    if value not in allowed:
        raise errors.invalid_request(f"{name} must be one of {sorted(allowed)}.")
    return value


# ---------------------------------------------------------------------------
# Datetime parsing for ISO 8601 input fields & clock comparisons
# ---------------------------------------------------------------------------
def parse_iso(value, name):
    if not isinstance(value, str):
        raise errors.invalid_request(f"{name} must be an ISO 8601 string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"{name} must be a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
