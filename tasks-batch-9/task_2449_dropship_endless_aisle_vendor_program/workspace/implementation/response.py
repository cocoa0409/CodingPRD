"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import api_error

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        meta.update(extra)
    return meta


def envelope(response_type, data, meta_extra=None):
    return {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }


def ok(data, status=200):
    return jsonify(envelope("object", data)), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(rows)) < total_count,
    }
    return jsonify(envelope("array", rows, meta_extra)), 200


def error_response(error_id, message, http_status):
    body = envelope("error", {"error_id": error_id, "message": message})
    return jsonify(body), http_status


def _int_param(args, name, default, minimum, maximum):
    if name not in args:
        return default
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        api_error("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        api_error("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        api_error("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, maximum))
    return value


def pagination(args):
    limit = _int_param(args, "limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param(args, "offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
