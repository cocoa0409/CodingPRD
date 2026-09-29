"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""
import random
import string

from flask import jsonify, request

import clock
from constants import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import invalid

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.wall_now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        invalid("Query parameter '%s' must be an integer." % name)
        return None
    if value < minimum or (maximum is not None and value > maximum):
        invalid("Query parameter '%s' is out of range." % name)
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0).  Out-of-range
    values are ERR_INVALID_REQUEST rather than being silently clamped."""
    limit = _query_int("limit", DEFAULT_LIMIT, MIN_LIMIT, MAX_LIMIT)
    offset = _query_int("offset", DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)


def query_enum(name, members):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        invalid("Query parameter '%s' is not a declared member." % name)
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = str(raw).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    invalid("Query parameter '%s' must be a boolean." % name)


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
