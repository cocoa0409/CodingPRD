"""Shared helpers: common-field stamping, datetime parsing, rounding, validation."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError, ERR_VALIDATION


# ---------------------------------------------------------------------------
# Common system fields (PRD 2.4): id, created_at, updated_at, version
# ---------------------------------------------------------------------------
def stamp_create(entity):
    ts = db.now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Any mutation refreshes updated_at and increments version (PRD 2.4)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


# ---------------------------------------------------------------------------
# Rounding (PRD 2.8): round half up at each named step.
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> int cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_half_up_1dp(value):
    """Round a number to one decimal place, half up (reliability score)."""
    q = Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Datetime parsing for ISO-8601 instants supplied in request bodies.
# ---------------------------------------------------------------------------
def parse_iso(value):
    if not isinstance(value, str):
        raise ApiError(*ERR_VALIDATION, message="timestamp must be an ISO-8601 string")
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(*ERR_VALIDATION, message="invalid ISO-8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Body field extraction with type validation -> ERR_VALIDATION (PRD 2.5).
# ---------------------------------------------------------------------------
def require_body(body):
    if body is None or not isinstance(body, dict):
        raise ApiError(*ERR_VALIDATION, message="request body must be a JSON object")
    return body


def req_str(body, name):
    if name not in body or not isinstance(body[name], str) or body[name] == "":
        raise ApiError(*ERR_VALIDATION, message=f"missing or invalid field: {name}")
    return body[name]


def req_int(body, name):
    val = body.get(name, None)
    if name not in body or isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(*ERR_VALIDATION, message=f"missing or invalid integer field: {name}")
    return val


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError(*ERR_VALIDATION, message=f"invalid integer field: {name}")
    return val


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], str):
        raise ApiError(*ERR_VALIDATION, message=f"invalid string field: {name}")
    return body[name]


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    if not isinstance(body[name], bool):
        raise ApiError(*ERR_VALIDATION, message=f"invalid boolean field: {name}")
    return body[name]


def req_enum(body, name, allowed):
    val = req_str(body, name)
    if val not in allowed:
        raise ApiError(*ERR_VALIDATION, message=f"invalid value for {name}")
    return val


def req_array_of_int(body, name):
    val = body.get(name, None)
    if name not in body or not isinstance(val, list) or len(val) == 0:
        raise ApiError(*ERR_VALIDATION, message=f"missing or invalid array field: {name}")
    for item in val:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ApiError(*ERR_VALIDATION, message=f"array {name} must contain integers")
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 / min 1 / max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination(args):
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError(*ERR_VALIDATION, message="limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(*ERR_VALIDATION, message="limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError(*ERR_VALIDATION, message="offset must be an integer")
        if offset < 0:
            raise ApiError(*ERR_VALIDATION, message="offset must be non-negative")
    return limit, offset


def paginate(rows, limit, offset):
    """rows: list already filtered. Returns (page, meta_pagination_dict)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def sorted_by_created(rows):
    # PRD 2.3: sorted by created_at ascending (oldest first). _seq breaks ties.
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
