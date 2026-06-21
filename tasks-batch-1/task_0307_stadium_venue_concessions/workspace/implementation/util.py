"""Shared utilities: rounding, validation primitives, serialization, pagination.

All money/percentage rounding uses round-half-up to whole cents (PRD §2.6).
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import store


# ---------------------------------------------------------------------------
# Rounding (PRD §2.6: round-half-up to whole cents)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest integer, half rounding UP.

    `value` may be int, float, or Decimal. We coerce through Decimal(str(...))
    to avoid binary-float artifacts.
    """
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(amount_cents, pct):
    """round_half_up(amount_cents * pct / 100) with exact decimal arithmetic."""
    result = Decimal(amount_cents) * Decimal(str(pct)) / Decimal(100)
    return round_half_up(result)


# ---------------------------------------------------------------------------
# Request-body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON body as a dict, or {} when there is no body.

    A body that is present but not a JSON object is malformed (ERR_INVALID_REQUEST).
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Field validators (raise ERR_INVALID_REQUEST on failure)
# ---------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}.")
    return body[name]


def as_nonempty_string(value, name, max_len=None):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string.")
    if max_len is not None and len(value) > max_len:
        raise errors.invalid_request(f"Field {name} exceeds max length {max_len}.")
    return value


def as_int(value, name):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    return value


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number.")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean.")
    return value


def as_enum(value, name, allowed):
    if value not in allowed:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(allowed)}.")
    return value


def as_pct(value, name):
    """0 <= value <= 100, up to 2 decimals (Venue percentages, PRD §3.1)."""
    num = as_number(value, name)
    if num < 0 or num > 100:
        raise errors.invalid_request(f"Field {name} must be between 0 and 100.")
    return num


def parse_datetime(value, name):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request(f"Field {name} must be an ISO 8601 datetime string.")
    raw = value
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Field {name} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Existence lookup (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def lookup(collection, ident):
    obj = collection.get(ident)
    if obj is None:
        raise errors.not_found()
    return obj


# ---------------------------------------------------------------------------
# Common system fields + mutation bookkeeping (PRD §2.4, §2.5)
# ---------------------------------------------------------------------------
def stamp_create(obj, with_version=True):
    """Attach id/created_at/updated_at/version to a fresh entity.

    with_version=False is used only for WasteRecord, which carries only id and
    created_at (PRD §2.4).
    """
    now = store.now()
    obj["id"] = store.new_id()
    obj["created_at"] = now
    obj["_seq"] = store.next_seq()
    if with_version:
        obj["updated_at"] = now
        obj["version"] = 1
    return obj


def touch(obj):
    """Record a mutation: refresh updated_at and bump version (PRD §2.5)."""
    obj["updated_at"] = store.now()
    obj["version"] = obj.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — params named limit/offset
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def sort_by_created(items):
    """Sort by created_at ascending, breaking ties by insertion sequence
    (PRD §2.3 default ordering)."""
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
