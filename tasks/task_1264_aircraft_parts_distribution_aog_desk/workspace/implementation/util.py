"""Response envelope, datetime, decimal and payload validation helpers."""

import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST


def new_id():
    return str(uuid.uuid4())


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=16))


def _wall_ts():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 string to an aware UTC datetime; raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(x):
    """Round half-up to a whole-cent integer."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_div(a, b):
    return -(-int(a) // int(b))


def success(data, code=200, response_type="object", pagination=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": _wall_ts()}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _wall_ts()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_body():
    """Return the JSON request body as a dict ({} when absent)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


# ---- payload field validators (raise ApiError 400) ----

def bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def req_present(body, name):
    if name not in body or body[name] is None:
        bad(f"Missing required field: {name}")
    return body[name]


def as_str(v, name):
    if not isinstance(v, str) or v == "":
        bad(f"Field {name} must be a non-empty string")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        bad(f"Field {name} must be a boolean")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        bad(f"Field {name} must be an integer")
    return v


def as_num(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad(f"Field {name} must be a number")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        bad(f"Field {name} must be one of {sorted(allowed)}")
    return v


def as_dt(v, name):
    try:
        return parse_dt(v)
    except Exception:
        bad(f"Field {name} must be a valid ISO 8601 timestamp")


def as_list(v, name):
    if not isinstance(v, list):
        bad(f"Field {name} must be an array")
    return v


# ---- pagination ----

def page_params():
    q = request.args
    try:
        limit = int(q.get("limit", 10))
    except (TypeError, ValueError):
        bad("limit must be an integer")
    try:
        offset = int(q.get("offset", 0))
    except (TypeError, ValueError):
        bad("offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paged(records, limit, offset):
    """records: pre-sorted list of serialized dicts."""
    total = len(records)
    window = records[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }
    return success(window, 200, "array", pagination)
