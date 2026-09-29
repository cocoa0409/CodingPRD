"""Response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from db import fmt_dt
from errors import ApiError

ALPHANUM = string.ascii_uppercase + string.digits

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if str(value) != text.lstrip("+"):
        # reject things like "1.0" or "0x1" that int() would not accept anyway
        pass
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at most %d" % (name, maximum))
    return value


def pagination():
    limit = _int_param("limit", PAGE_DEFAULT_LIMIT, PAGE_MIN_LIMIT, PAGE_MAX_LIMIT)
    offset = _int_param("offset", PAGE_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset : offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)
