"""Shared helpers: response envelope, errors, decimal/datetime handling, field validation."""
import secrets
import uuid
from datetime import datetime, date, time, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, InvalidOperation

from flask import jsonify, request

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def api_err(error_id, status, message):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Wall-clock timestamps (created_at / updated_at / meta). Monotonic at ms
# resolution so created_at ordering is strict even for rapid sequences.
# ---------------------------------------------------------------------------
_last_wall = None


def wall_now_dt():
    global _last_wall
    t = datetime.now(timezone.utc)
    t = t.replace(microsecond=(t.microsecond // 1000) * 1000)
    if _last_wall is not None and t <= _last_wall:
        t = _last_wall + timedelta(milliseconds=1)
    _last_wall = t
    return t


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    return fmt_dt(wall_now_dt())


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + secrets.token_hex(12)


# ---------------------------------------------------------------------------
# Response envelope (per SCAFFOLD response_envelope / PRD section 2.2)
# ---------------------------------------------------------------------------
def success(data, status=200, pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(e):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_now(),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------
def rhu(value, quantum=TWO):
    """Round half up to the given quantum (default 2dp)."""
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def floor2(value):
    return value.quantize(TWO, rounding=ROUND_FLOOR)


def ser_val(v):
    """JSON-serialize a record value: Decimal -> float, recursing containers."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return [ser_val(i) for i in v]
    if isinstance(v, dict):
        return {k: ser_val(x) for k, x in v.items()}
    return v


def serialize(rec, fields):
    return {f: ser_val(rec.get(f)) for f in fields}


# ---------------------------------------------------------------------------
# Datetime parsing. Input datetime fields keep their raw string for echo and
# carry a parsed UTC datetime under a "_dt_<name>" key.
# ---------------------------------------------------------------------------
def parse_dt_value(v):
    """Parse an ISO 8601 date or datetime string to an aware UTC datetime."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s:
        return None
    cand = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    dt = None
    try:
        dt = datetime.fromisoformat(cand)
    except ValueError:
        try:
            dt = datetime.combine(date.fromisoformat(s), time.min)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Request body validation helpers (all failures -> ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------
def invalid(msg):
    api_err("ERR_INVALID_REQUEST", 400, msg)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("request body must be a JSON object")
    return data


def check_unknown(data, allowed):
    extra = [k for k in data.keys() if k not in allowed]
    if extra:
        invalid(f"unknown field(s): {', '.join(sorted(extra))}")


def fld_string(data, name, required=True):
    v = data.get(name)
    if v is None:
        if required:
            invalid(f"missing required field: {name}")
        return None
    if not isinstance(v, str) or v == "":
        invalid(f"field {name} must be a non-empty string")
    return v


def fld_decimal(data, name, required=True, gt=None, gte=None, lte=None):
    v = data.get(name)
    if v is None:
        if required:
            invalid(f"missing required field: {name}")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        invalid(f"field {name} must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        invalid(f"field {name} must be a number")
    if not d.is_finite():
        invalid(f"field {name} must be a finite number")
    if gt is not None and not d > Decimal(str(gt)):
        invalid(f"field {name} must be > {gt}")
    if gte is not None and not d >= Decimal(str(gte)):
        invalid(f"field {name} must be >= {gte}")
    if lte is not None and not d <= Decimal(str(lte)):
        invalid(f"field {name} must be <= {lte}")
    return d


def fld_int(data, name, required=True, gt=None, gte=None):
    d = fld_decimal(data, name, required=required, gt=gt, gte=gte)
    if d is None:
        return None
    if d != d.to_integral_value():
        invalid(f"field {name} must be an integer")
    return int(d)


def fld_enum(data, name, choices, required=True, default=None):
    v = data.get(name)
    if v is None:
        if required:
            invalid(f"missing required field: {name}")
        return default
    if not isinstance(v, str) or v not in choices:
        invalid(f"field {name} must be one of: {', '.join(choices)}")
    return v


def fld_dt(data, name, required=True):
    """Returns (raw_string, parsed_utc_datetime)."""
    v = data.get(name)
    if v is None:
        if required:
            invalid(f"missing required field: {name}")
        return None, None
    dt = parse_dt_value(v)
    if dt is None:
        invalid(f"field {name} must be an ISO 8601 date/datetime")
    return v, dt


def fld_version(data, name):
    """OCC field: required integer. Missing/non-integer -> 400; caller compares."""
    return fld_int(data, name, required=True)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, capped at 100; offset default 0
# ---------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not str(raw_limit).strip().lstrip("+").isdigit():
            invalid("limit must be an integer")
        if limit < 1:
            invalid("limit must be at least 1")
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset must be at least 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def sort_created(items):
    """created_at strings are fixed-format UTC, so lexicographic == chronological."""
    return sorted(items, key=lambda r: r["created_at"])
