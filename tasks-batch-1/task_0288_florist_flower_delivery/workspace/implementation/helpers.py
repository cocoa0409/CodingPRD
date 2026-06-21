"""Shared helpers: body parsing, pagination, money rounding, common fields."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import store, new_id, now_iso


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.5: round-half-up at each fractional step)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half rounds up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Parse the JSON request body; missing/empty body becomes {}.
    A malformed JSON body raises ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset. Out-of-range/non-integer values are rejected with
    ERR_INVALID_REQUEST. Defaults: limit=10 (min 1, max 100), offset=0 (min 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit out of range [1,100]")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at asc (insertion sequence as deterministic tie-break),
    then apply offset/limit. Returns (page_items, total_count)."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Common system fields (PRD §2.4)
# ---------------------------------------------------------------------------
def make_record(with_version=True):
    """Create a record skeleton with id/created_at/updated_at/version.
    DeliverySlot and ClockState pass with_version=False (id + created_at only)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
    }
    if with_version:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record as mutated: refresh updated_at, bump version by 1."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal-only fields (those prefixed with '_') for the response."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Validation primitives
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request("Missing required field: %s" % n)


def as_int(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("%s must be an integer" % name)
    return val


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.invalid_request("%s must be a string" % name)
    return val


def as_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request("%s must be a boolean" % name)
    return val


def as_number(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("%s must be a number" % name)
    return val


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if val not in allowed:
        raise errors.invalid_request("%s must be one of %s" % (name, sorted(allowed)))
    return val
