"""Standard response envelope helpers (PRD 2.2, 2.3)."""
from flask import jsonify, request

from db import new_request_id, now_iso
from errors import invalid_request


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination:
        body["meta"].update(pagination)
    return jsonify(body), status


def created(data):
    return ok(data, "object", 201)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise invalid_request(f"Query parameter '{name}' must be an integer")


def paginated(items):
    """items: full list, already sorted by created_at ascending.
    Pagination: limit (default 10, min 1, max 100), offset (default 0)."""
    args = request.args
    if "limit" in args:
        limit = _parse_int_param(args.get("limit"), "limit")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    else:
        limit = 10
    if "offset" in args:
        offset = _parse_int_param(args.get("offset"), "offset")
        if offset < 0:
            offset = 0
    else:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return ok(
        page,
        "array",
        200,
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        },
    )


def sorted_items(records):
    """Sort by created_at ascending (insertion order breaks ties)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
