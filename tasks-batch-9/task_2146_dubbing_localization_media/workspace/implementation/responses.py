"""Standard response envelope helpers (PRD section 2.2)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import fmt_ms, now

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ms(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _parse_page_param(raw, default, minimum, maximum):
    if raw is None:
        return default
    if isinstance(raw, str):
        text = raw.strip()
    else:
        text = raw
    if text == "" or text is None:
        raise ApiError("ERR_INVALID_PAGINATION")
    try:
        value = int(str(text), 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_PAGINATION")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_PAGINATION")
    return value


def pagination():
    """Returns (limit, offset), raising ERR_INVALID_PAGINATION when malformed."""
    limit = _parse_page_param(request.args.get("limit"), 10, 1, 100)
    offset = _parse_page_param(request.args.get("offset"), 0, 0, None)
    return limit, offset


def paged(rows, serializer):
    from store import sort_key
    limit, offset = pagination()
    ordered = sorted(rows, key=sort_key)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
