"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def ok(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, page_meta, status=200):
    meta = base_meta()
    meta.update(page_meta)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    neg = text.startswith("-")
    digits = text[1:] if neg else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be an integer" % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' is below the permitted minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' exceeds the permitted maximum" % name)
    return value


def pagination():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(rows, serializer):
    """rows must already be in the endpoint's declared sort order."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok_list([serializer(r) for r in page], meta)


def filter_enum(name, allowed):
    """Read an optional query filter constrained to a declared enum."""
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' carries a value outside the declared enum" % name)
    return raw


def filter_str(name):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return None
    return raw
