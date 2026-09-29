"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

from errors import err
from store import real_now_iso

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": real_now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_response(error_id, http_status, message):
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
    txt = raw.strip()
    negative = txt.startswith("-")
    digits = txt[1:] if negative or txt.startswith("+") else txt
    if not digits.isdigit():
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(txt)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "%s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "%s is above its maximum." % name)
    return value


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginated(items, serializer):
    """items must already be in the endpoint's declared order."""
    limit, offset = pagination()
    total = len(items)
    window = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": real_now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(window)) < total,
        },
        "response_type": "array",
        "data": [serializer(i) for i in window],
    }
    return jsonify(body), 200
