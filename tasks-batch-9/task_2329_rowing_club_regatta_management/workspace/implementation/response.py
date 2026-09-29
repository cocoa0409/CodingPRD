"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

import clock
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": clock.now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def ok_array(items):
    """An array payload that is not a paginated listing (operator checkpoints)."""
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d." % (name, maximum))
    return value


def page():
    """Return (limit, offset) from the query string, validated per PRD 2.3."""
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = page()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def filters(*names):
    """Collect the supplied equality filters from the query string."""
    out = {}
    for name in names:
        raw = request.args.get(name)
        if raw is not None and raw != "":
            out[name] = raw
    return out


def matches(rec, wanted):
    for key, value in wanted.items():
        actual = rec.get(key)
        if isinstance(actual, list):
            if value not in actual:
                return False
        elif isinstance(actual, bool):
            if str(value).strip().lower() not in ("true", "false"):
                return False
            if actual is not (str(value).strip().lower() == "true"):
                return False
        elif actual is None:
            return False
        elif str(actual) != str(value):
            return False
    return True
