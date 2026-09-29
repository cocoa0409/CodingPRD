"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def respond_object(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if value < minimum:
        raise ApiError(
            "ERR_INVALID_REQUEST", "%s must be at least %d" % (name, minimum)
        )
    if maximum is not None and value > maximum:
        raise ApiError(
            "ERR_INVALID_REQUEST", "%s must be at most %d" % (name, maximum)
        )
    return value


def pagination():
    limit = _int_param(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(records, serializer):
    """Apply created_at-ascending ordering plus limit/offset paging."""
    limit, offset = pagination()
    total = len(records)
    page = records[offset : offset + limit]
    return respond_list([serializer(r) for r in page], limit, offset, total)


def allowed_query(*names):
    """Reject unknown query parameters on a collection endpoint."""
    known = set(names) | {"limit", "offset"}
    for key in request.args.keys():
        if key not in known:
            raise ApiError("ERR_INVALID_REQUEST", "unknown query parameter %s" % key)
