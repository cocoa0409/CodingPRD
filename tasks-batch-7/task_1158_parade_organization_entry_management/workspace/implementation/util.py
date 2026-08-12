"""Response envelope, timestamps, request parsing, validators, pagination."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import api_err


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _wall_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _wall_ts()}


def respond_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def respond_list(data, limit, offset, total_count):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(data)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": data}), 200


def respond_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Logical-clock rendering: seconds precision when no fraction is set."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise api_err("ERR_VALIDATION", f"{field} must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise api_err("ERR_VALIDATION", f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Request body + field validators (schema violations -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise api_err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise api_err("ERR_VALIDATION", f"{field} is required and must be a non-empty string")
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise api_err("ERR_VALIDATION", f"{field} must be a string")
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if not _is_int(v):
        raise api_err("ERR_VALIDATION", f"{field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise api_err("ERR_VALIDATION", f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise api_err("ERR_VALIDATION", f"{field} must be <= {maximum}")
    return v


def opt_int(data, field, minimum=None):
    v = data.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise api_err("ERR_VALIDATION", f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise api_err("ERR_VALIDATION", f"{field} must be >= {minimum}")
    return v


def req_num(data, field, minimum=None, exclusive_min=False):
    v = data.get(field)
    if not _is_num(v):
        raise api_err("ERR_VALIDATION", f"{field} is required and must be a number")
    if minimum is not None:
        if exclusive_min and not v > minimum:
            raise api_err("ERR_VALIDATION", f"{field} must be > {minimum}")
        if not exclusive_min and not v >= minimum:
            raise api_err("ERR_VALIDATION", f"{field} must be >= {minimum}")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise api_err("ERR_VALIDATION", f"{field} must be one of {sorted(allowed)}")
    return v


def req_dt(data, field):
    if field not in data or data.get(field) is None:
        raise api_err("ERR_VALIDATION", f"{field} is required")
    return parse_dt(data.get(field), field)


def req_str_list(data, field):
    v = data.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise api_err("ERR_VALIDATION", f"{field} must be an array of strings")
    return v


# ---------------------------------------------------------------------------
# Pagination (limit default 10, min 1, max 100; offset default 0, min 0)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise api_err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_err("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise api_err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise api_err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paged(items, serializer):
    """items: full filtered collection; sorted by created_at ascending (stable)."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)
