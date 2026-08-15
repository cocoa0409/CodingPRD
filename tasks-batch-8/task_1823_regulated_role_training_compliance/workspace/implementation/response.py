"""Response envelope (PRD 2.2), pagination (2.3), and entity serialization."""
import uuid
from datetime import datetime
from decimal import Decimal

from flask import jsonify, request

from db import now
from errors import ApiError, bad_request
from util import fmt_dt


def _jsonable(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def pub(e):
    """Public view of an entity: drop internal ('_'-prefixed) fields, format values."""
    return {k: _jsonable(v) for k, v in e.items() if not k.startswith("_")}


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_dt(now()),
    }


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0. Out-of-range clamps."""
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (ValueError, TypeError):
            raise bad_request("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (ValueError, TypeError):
            raise bad_request("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def list_response(items, already_serialized=False):
    """All list endpoints: created_at-ascending collections with pagination meta."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    data = page if already_serialized else [pub(e) for e in page]
    return success(data, "array", 200, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })


def get_body():
    """JSON body as dict; missing/malformed/non-object body -> ERR_INVALID_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad_request("request body must be a JSON object")
    return body


_MISSING = object()


def req_field(body, name):
    v = body.get(name, _MISSING)
    if v is _MISSING or v is None:
        raise bad_request("missing required field: %s" % name)
    return v


def req_str(body, name, min_len=1):
    v = req_field(body, name)
    if not isinstance(v, str) or len(v) < min_len:
        raise bad_request("field %s must be a string of length >= %d" % (name, min_len))
    return v


def opt_str(body, name, allow_null=True):
    if name not in body:
        return None
    v = body[name]
    if v is None:
        if allow_null:
            return None
        raise bad_request("field %s must be a string" % name)
    if not isinstance(v, str):
        raise bad_request("field %s must be a string" % name)
    return v


def req_int(body, name, lo=None, hi=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request("field %s must be an integer" % name)
    if lo is not None and v < lo:
        raise bad_request("field %s below minimum %d" % (name, lo))
    if hi is not None and v > hi:
        raise bad_request("field %s above maximum %d" % (name, hi))
    return v


def opt_int(body, name, lo=None, hi=None, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request("field %s must be an integer" % name)
    if lo is not None and v < lo:
        raise bad_request("field %s below minimum %d" % (name, lo))
    if hi is not None and v > hi:
        raise bad_request("field %s above maximum %d" % (name, hi))
    return v


def req_enum(body, name, choices):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in choices:
        raise bad_request("field %s must be one of %s" % (name, "/".join(choices)))
    return v


def opt_enum(body, name, choices):
    if name not in body or body[name] is None:
        return None
    v = body[name]
    if not isinstance(v, str) or v not in choices:
        raise bad_request("field %s must be one of %s" % (name, "/".join(choices)))
    return v


def req_dt(body, name):
    from util import parse_dt
    v = req_field(body, name)
    dt = parse_dt(v)
    if dt is None:
        raise bad_request("field %s must be an ISO-8601 timestamp" % name)
    return dt


def opt_dt(body, name):
    from util import parse_dt
    if name not in body or body[name] is None:
        return None
    dt = parse_dt(body[name])
    if dt is None:
        raise bad_request("field %s must be an ISO-8601 timestamp" % name)
    return dt


def opt_decimal(body, name, lo=None, hi=None, max_dp=None, default=None):
    from util import parse_decimal
    if name not in body or body[name] is None:
        return default
    d = parse_decimal(body[name], lo, hi, max_dp)
    if d is None:
        raise bad_request("field %s must be a number in range" % name)
    return d


def req_decimal(body, name, lo=None, hi=None, max_dp=None):
    from util import parse_decimal
    v = req_field(body, name)
    d = parse_decimal(v, lo, hi, max_dp)
    if d is None:
        raise bad_request("field %s must be a number in range" % name)
    return d
