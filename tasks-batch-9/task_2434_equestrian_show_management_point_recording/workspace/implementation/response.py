"""Response envelope helpers (PRD section 2.2 / scaffold response_envelope)."""

import random
import string

from flask import jsonify, request

from core import commit, iso_ms
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    commit()
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, total_count, limit, offset):
    commit()
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is above its maximum." % name)
    return value


def pagination():
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginated(rows, serializer):
    """Sort-stable window over a filtered collection."""
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset: offset + limit]
    return array_response([serializer(r) for r in window], total, limit, offset)
