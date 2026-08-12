"""Shared helpers: decimal money, timestamps, validation, envelope, pagination."""
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

from errors import ApiError, err_validation
from store import DB

CENT = Decimal("0.01")

# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def D(x):
    """Coerce to Decimal safely (via str for floats)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(x))


def r2(x):
    """Round half-up to exactly 2 decimal places."""
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


def money(x):
    """Serialize a monetary Decimal as a JSON number with at most 2dp."""
    return float(r2(x))


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_instant(dt):
    """ISO8601 UTC; seconds precision unless the value carries fractions."""
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_ts():
    return fmt_ts(datetime.now(timezone.utc))


def next_ts():
    """Monotonic timestamp rooted in the logical clock (never goes backward)."""
    cand = DB.clock
    if cand <= DB._last_ts:
        cand = DB._last_ts + timedelta(milliseconds=1)
    DB._last_ts = cand
    return fmt_ts(cand)


def touch(entity):
    """Refresh updated_at and bump version on a common-fields entity."""
    entity["updated_at"] = next_ts()
    entity["version"] = entity.get("version", 0) + 1


def new_entity(common=True):
    e = {"id": str(uuid.uuid4())}
    ts = next_ts()
    e["created_at"] = ts
    if common:
        e["updated_at"] = ts
        e["version"] = 1
    e["_seq"] = next(DB._insert_seq)
    return e


def parse_dt(value, field):
    """Parse an ISO8601 datetime; ERR_VALIDATION on failure."""
    if not isinstance(value, str):
        raise err_validation(f"Field '{field}' must be an ISO8601 string")
    v = value.strip()
    try:
        if v.endswith("Z"):
            dt = datetime.fromisoformat(v[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(v)
    except ValueError:
        raise err_validation(f"Field '{field}' is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Body field validation
# ---------------------------------------------------------------------------

def body():
    return request.get_json(silent=True) or {}


def need(b, name):
    if name not in b or b[name] is None:
        raise err_validation(f"Missing required field: {name}")
    return b[name]


def as_str(v, name):
    if not isinstance(v, str) or isinstance(v, bool):
        raise err_validation(f"Field '{name}' must be a string")
    return v


def as_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation(f"Field '{name}' must be a number")
    return D(v)


def as_money(v, name):
    """Numeric field stored as Decimal (2dp semantics applied by callers)."""
    return as_number(v, name)


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"Field '{name}' must be an integer")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise err_validation(f"Field '{name}' must be a boolean")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(
            f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def get_or_404(collection, ident, entity):
    from errors import err_not_found
    obj = collection.get(ident)
    if obj is None:
        raise err_not_found(entity)
    return obj


# ---------------------------------------------------------------------------
# Response envelope (fixed by scaffold): meta/response_type/data
# ---------------------------------------------------------------------------

def _meta():
    return {"api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": wall_ts()}


def respond(data, code=200):
    payload = {"meta": _meta(),
               "response_type": "array" if isinstance(data, list) else "object",
               "data": data}
    return jsonify(payload), code


def respond_error(error_id, status, message):
    payload = {"meta": _meta(),
               "response_type": "error",
               "data": {"error_id": error_id, "message": message}}
    return jsonify(payload), status


def paginate(items):
    """limit/offset pagination with defaults 10/0, clamped to [1,100]/[0,...]."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {"limit": limit, "offset": offset,
            "total_count": total, "has_more": offset + len(page) < total}
    return page, meta


def respond_list(items, serializer, code=200):
    page, meta = paginate(items)
    payload = {"meta": {**_meta(), **meta},
               "response_type": "array",
               "data": [serializer(e) for e in page]}
    return jsonify(payload), code
