"""Response envelope helpers, timestamps, numeric coercion, and field parsing."""

import re
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

import db
from errors import raise_err, ERR_VALIDATION

_ALNUM = string.ascii_letters + string.digits


def _request_id() -> str:
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def _wall_timestamp() -> str:
    return fmt_dt(datetime.now(timezone.utc))


def fmt_dt(dt) -> str:
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id: str, message: str):
    return {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination(args):
    """Reads limit/offset query params per spec: default 10/0, limit in [1,100]."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Sorts by creation order, applies limit/offset, returns (page, limit, offset, total)."""
    limit, offset = parse_pagination(args)
    ordered = sorted(items, key=lambda e: e.get("_seq", 0))
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Body field parsing / schema validation
# ---------------------------------------------------------------------------

def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise_err(ERR_VALIDATION, f"missing required field: {name}")
    return body[name]


def as_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise_err(ERR_VALIDATION, f"missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"{name} must be a string")
    return v


def as_enum(body, name, allowed, required=True):
    v = as_str(body, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        raise_err(ERR_VALIDATION, f"{name} must be one of {sorted(allowed)}")
    return v


def as_decimal(body, name, required=True, gt=None, ge=None):
    from decimal import Decimal, InvalidOperation
    if name not in body or body[name] is None:
        if required:
            raise_err(ERR_VALIDATION, f"missing required field: {name}")
        return None
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise_err(ERR_VALIDATION, f"{name} must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise_err(ERR_VALIDATION, f"{name} must be a number")
    if not d.is_finite():
        raise_err(ERR_VALIDATION, f"{name} must be a finite number")
    if gt is not None and not (d > Decimal(str(gt))):
        raise_err(ERR_VALIDATION, f"{name} must be > {gt}")
    if ge is not None and not (d >= Decimal(str(ge))):
        raise_err(ERR_VALIDATION, f"{name} must be >= {ge}")
    return d


def as_int(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise_err(ERR_VALIDATION, f"missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"{name} must be an integer")
    return v


def as_list(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise_err(ERR_VALIDATION, f"missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, list):
        raise_err(ERR_VALIDATION, f"{name} must be an array")
    return v


_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(value, field_name="datetime"):
    """Parse an ISO 8601 string into an aware UTC datetime; naive -> assume UTC."""
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        raise_err(ERR_VALIDATION, f"{field_name} must be an ISO 8601 datetime string")
    s = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    # tolerate offset without colon
    if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_VALIDATION, f"{field_name} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def as_datetime(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            raise_err(ERR_VALIDATION, f"missing required field: {name}")
        return None
    return parse_datetime(body[name], name)


# ---------------------------------------------------------------------------
# Numeric output coercion
# ---------------------------------------------------------------------------

def jn(d):
    """Decimal -> JSON-native number: int when integral, else float."""
    if d is None:
        return None
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def touch(entity):
    """Every mutation refreshes updated_at and increments version."""
    entity["version"] += 1
    entity["updated_at"] = fmt_dt(db.clock_now())


def new_common(entity):
    now = fmt_dt(db.clock_now())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity
