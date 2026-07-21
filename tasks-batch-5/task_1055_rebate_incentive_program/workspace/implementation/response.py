"""Response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import err

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginated(items, serializer):
    """items must already be in the desired order."""
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": [serializer(i) for i in page],
    }
    body["meta"]["limit"] = limit
    body["meta"]["offset"] = offset
    body["meta"]["total_count"] = total
    body["meta"]["has_more"] = offset + len(page) < total
    return jsonify(body), 200


def array_response(items, serializer, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": [serializer(i) for i in items],
    }
    return jsonify(body), status
