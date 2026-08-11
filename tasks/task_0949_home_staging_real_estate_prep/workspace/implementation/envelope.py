"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_ts()}


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(name, default, low, high=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if value < low or (high is not None and value > high):
        raise ApiError("ERR_INVALID_REQUEST", "%s is out of its permitted range." % name)
    return value


def pagination():
    """Rung 8 on paginated GET endpoints: limit 1..100, offset >= 0."""
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def paginate(rows, serializer, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qs_bool(name):
    value = qs(name)
    if value is None:
        return None
    return str(value).strip().lower() in ("true", "1", "yes")
