"""Response envelope helpers -- field names taken from PRD section 2.2 /
SCAFFOLD response_envelope.

success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""

from flask import jsonify, request

from errors import ApiError
from store import iso_ms, new_request_id, store

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_ms(store.wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created_rows_response(items, status=201):
    """An array envelope for an operation that created several rows at once.

    §2.2 reserves the pagination fields in `meta` for list endpoints, so they
    are absent here; `response_type` is "array" because `data` carries an array
    of resource objects.
    """
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status


def array_response(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s must be <= %d" % (name, maximum))
    return value


def pagination():
    """Returns (limit, offset), validated against the declared defaults."""
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paged(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)


def query_flag(name):
    """Parse a boolean query filter; returns None when absent."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = raw.strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    raise ApiError("ERR_VALIDATION", "%s must be a boolean" % name)


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return _query_int(name, None, None, None)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
