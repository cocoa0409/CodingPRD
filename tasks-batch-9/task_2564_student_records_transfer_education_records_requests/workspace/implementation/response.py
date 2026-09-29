"""Standard response envelope (PRD 2.2)."""

from flask import jsonify

from common import clock_now, iso, new_request_id, pagination, sorted_rows


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(clock_now()),
    }


def ok(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(payload), status


def created(data):
    return ok(data, 201)


def empty(status=200):
    return ok({}, status)


def listing(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(payload), status


def paginate(rows, serializer, presorted=False):
    """Apply the default created_at ascending sort, then limit/offset."""
    limit, offset = pagination()
    ordered = rows if presorted else sorted_rows(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return listing([serializer(row) for row in page], limit, offset, total)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
