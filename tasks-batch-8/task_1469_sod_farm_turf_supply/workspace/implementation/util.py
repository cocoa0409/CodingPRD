"""Shared helpers: timestamps, decimals, envelope, validation primitives."""
import random
import string
from datetime import datetime, timezone, date

from decimal import Decimal, ROUND_HALF_UP
from flask import jsonify, request

import db
from errors import err, ERR_INVALID_REQUEST

TWO_DP = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


# ---------------------------------------------------------------- decimals
def D(x):
    """Coerce an int/float/str/Decimal to Decimal without float dust."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def r2(x):
    return D(x).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def r4(x):
    return D(x).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def money_out(x):
    """2dp money as a JSON number."""
    return float(r2(x))


def num_out(x):
    """Sqft-like quantity: int when integral, else float."""
    d = D(x)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------- timestamps
def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{field} must be a YYYY-MM-DD date string")


def hours_between(start, end):
    """Exact Decimal hours between two datetimes."""
    delta = end - start
    micros = Decimal(delta.days * 86400 + delta.seconds) * Decimal(1000000) + Decimal(delta.microseconds)
    return micros / Decimal(3600000000)


# ---------------------------------------------------------------- envelope
def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=16)),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


# ---------------------------------------------------------------- request utils
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return payload


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paged(items, limit, offset):
    """items must already be sorted by creation order."""
    total = len(items)
    return items[offset:offset + limit], total


def sort_created(items):
    return sorted(items, key=lambda e: e["_seq"])


# ---------------------------------------------------------------- field validation
def require(payload, name):
    if name not in payload or payload[name] is None:
        raise err(ERR_INVALID_REQUEST, f"{name} is required")
    return payload[name]


def as_str(value, name):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{name} must be a string")
    return value


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{name} must be an integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise err(ERR_INVALID_REQUEST, f"{name} must be an integer")
        value = int(value)
    if minimum is not None and value < minimum:
        raise err(ERR_INVALID_REQUEST, f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err(ERR_INVALID_REQUEST, f"{name} must be <= {maximum}")
    return value


def as_num(value, name, minimum=None, maximum=None, exclusive_minimum=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{name} must be a number")
    d = D(value)
    if minimum is not None:
        if exclusive_minimum and d <= D(minimum):
            raise err(ERR_INVALID_REQUEST, f"{name} must be > {minimum}")
        if not exclusive_minimum and d < D(minimum):
            raise err(ERR_INVALID_REQUEST, f"{name} must be >= {minimum}")
    if maximum is not None and d > D(maximum):
        raise err(ERR_INVALID_REQUEST, f"{name} must be <= {maximum}")
    return d


def as_bool(value, name):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, f"{name} must be a boolean")
    return value


def check_enum(value, allowed):
    return isinstance(value, str) and value in allowed
