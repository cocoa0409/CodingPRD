"""Response envelope helpers — exact structure from scaffold Table 1.0 / PRD §2.2."""

from flask import jsonify

from util import new_request_id, now_iso


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def success_object(data, code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def success_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def success_rows(rows, limit, offset, total_count):
    """Computed-read list payload: data wraps the array as {"rows": [...]} and
    meta carries the pagination fields."""
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(rows)) < total_count,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "object",
        "data": {"rows": rows},
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
