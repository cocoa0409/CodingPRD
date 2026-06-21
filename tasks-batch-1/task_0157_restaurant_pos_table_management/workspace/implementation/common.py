"""Shared helpers: body parsing, validation, pagination, common fields."""
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
import errors


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict (empty dict if none)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def require_str(body, name):
    val = body.get(name)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string.")
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = body.get(name)
    # bool is a subclass of int — reject it as a non-integer type
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {name} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field {name} must be <= {maximum}.")
    return val


def require_enum(body, name, choices):
    val = body.get(name)
    if val not in choices:
        raise errors.invalid_request(
            f"Field {name} must be one of {sorted(choices)}."
        )
    return val


def optional_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum, maximum)


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.5)
# ---------------------------------------------------------------------------
def round_half_up_bps(cents, bps):
    """round_half_up(cents * bps / 10000) -> integer cents."""
    if cents == 0 or bps == 0:
        return 0
    raw = Decimal(cents) * Decimal(bps) / Decimal(10000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_bps(cents, bps):
    """floor(cents * bps / 10000) -> integer cents."""
    return (cents * bps) // 10000


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_create(rec, clock_dt, versioned=True):
    """Set id/created_at (+ updated_at/version when versioned)."""
    now = db.iso_ms(clock_dt)
    rec["id"] = db.new_id()
    rec["_seq"] = db.next_seq()
    rec["created_at"] = now
    if versioned:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec, clock_dt):
    """Bump updated_at + version on a mutation (PRD §2.4)."""
    rec["updated_at"] = db.iso_ms(clock_dt)
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def paginate(rows):
    """Sort by created order, apply limit/offset, return (page, pagination_meta).

    Defaults: limit=10 (min 1, max 100, values above max capped to 100),
    offset=0 (min 0). Ordered by created_at ASC (the _seq counter).
    """
    limit = _parse_pagination_param("limit", default=10, minimum=1, maximum=100, cap=True)
    offset = _parse_pagination_param("offset", default=0, minimum=0, maximum=None, cap=False)

    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def _parse_pagination_param(name, default, minimum, maximum, cap):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Query parameter {name} must be an integer.")
    if val < minimum:
        raise errors.invalid_request(f"Query parameter {name} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        if cap:
            return maximum
        raise errors.invalid_request(f"Query parameter {name} must be <= {maximum}.")
    return val


# ---------------------------------------------------------------------------
# Existence lookup (left-to-right, PRD §2.6)
# ---------------------------------------------------------------------------
def must_exist(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found(f"Resource {rid} not found.")
    return rec
