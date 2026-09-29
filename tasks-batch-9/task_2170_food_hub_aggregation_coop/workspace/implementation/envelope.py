"""Standard success / error response envelopes (PRD 2.2) and pagination (2.3)."""

from flask import jsonify, request

from constants import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from errors import ApiError
from store import fmt_dt, new_request_id, now


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _parse_int_param(raw, name):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    try:
        return int(text, 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def pagination():
    """Returns (limit, offset); raises ERR_INVALID_REQUEST when out of range."""
    limit = _parse_int_param(request.args.get("limit"), "limit")
    offset = _parse_int_param(request.args.get("offset"), "offset")
    if limit is None:
        limit = DEFAULT_LIMIT
    if offset is None:
        offset = DEFAULT_OFFSET
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be greater than or equal to 0.")
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def list_response(records, serializer):
    """Sorted/filtered records -> paginated array envelope."""
    limit, offset = pagination()
    page, total = paginate(records, limit, offset)
    return ok_list([serializer(r) for r in page], limit, offset, total)
