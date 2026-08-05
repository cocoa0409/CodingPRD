"""The response envelope of PRD §2.2 and the pagination of §2.3."""

from flask import jsonify

import config
from errors import ApiError
from store import new_request_id, now_iso


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, code=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(rows) < total,
        }),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _page_int(raw, field, minimum, maximum=None):
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if text == "" or not re_int(text):
            raise ApiError("ERR_VALIDATION", "Pagination parameter '%s' must be an integer." % field)
        value = int(text)
    elif isinstance(raw, bool) or not isinstance(raw, int):
        raise ApiError("ERR_VALIDATION", "Pagination parameter '%s' must be an integer." % field)
    else:
        value = raw
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_VALIDATION", "Pagination parameter '%s' is out of range." % field)
    return value


def re_int(text):
    if text.startswith("+") or text.startswith("-"):
        text = text[1:]
    return text.isdigit() and text != ""


def pagination(args):
    """Rung 3: limit is 1..100 inclusive, offset >= 0."""
    limit = _page_int(args.get("limit"), "limit", config.PAGE_LIMIT_MIN, config.PAGE_LIMIT_MAX)
    offset = _page_int(args.get("offset"), "offset", 0)
    if limit is None:
        limit = config.PAGE_LIMIT_DEFAULT
    if offset is None:
        offset = config.PAGE_OFFSET_DEFAULT
    return limit, offset


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(r) for r in window], limit, offset, total)
