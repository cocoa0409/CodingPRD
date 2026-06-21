"""Common-field stamping, parsing, rounding, and time helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import new_id, next_seq, now_iso
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_WINDOW

ROLES = {
    "StoreManager",
    "ReceivingClerk",
    "PriceManager",
    "Cashier",
    "InventoryAuditor",
    "LoyaltyMember",
}


def stamp_new(record):
    """Attach common fields id/created_at/updated_at/version to a fresh record."""
    rid = new_id()
    ts = now_iso()
    record["id"] = rid
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump version + updated_at on a mutation that changed the record."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()


def public(record):
    """Strip internal-only fields (prefixed with _) for output."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def round_half_up(numerator, denominator):
    """Integer division of numerator/denominator rounded half up (away from zero
    for the .5 case). Numerator/denominator are integers; result is an int."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------- request body field parsing ----------------

def require_dict(body):
    if body is None or not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "request body must be a JSON object")
    return body


def get_str(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} is required")
        return default
    v = body[key]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} must be a string")
    return v


def get_int(body, key, required=True, default=None, min_value=None, max_value=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} is required")
        return default
    v = body[key]
    # bool is a subclass of int — reject it as a non-integer to avoid True==1 traps
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} must be <= {max_value}")
    return v


def get_bool(body, key, required=False, default=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} is required")
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} must be a boolean")
    return v


def get_enum(body, key, allowed, required=True, default=None):
    v = get_str(body, key, required=required, default=default)
    if v is None:
        return default
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} must be one of {sorted(allowed)}")
    return v


def parse_dt(value, key="datetime"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_dt(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"{key} is required")
        return default
    return parse_dt(body[key], key)


def validate_window(start_dt, end_dt):
    """effective_end must be strictly after effective_start, else ERR_INVALID_WINDOW."""
    if not (end_dt > start_dt):
        raise ApiError(ERR_INVALID_WINDOW[0], ERR_INVALID_WINDOW[1], "effective_end must be strictly after effective_start")


def pagination_params(args):
    """Parse limit/offset query params per PRD §2.3.
    limit default 10, min 1, max 100 (clamped above max). offset default 0.
    A limit below the minimum (or non-integer) is a malformed request."""
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "limit must be an integer")
        if limit < 1:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "limit must be >= 1")
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (then insertion seq) and slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
