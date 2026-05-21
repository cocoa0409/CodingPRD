from flask import jsonify, g
from .ids import new_request_id
from .clock import iso
from .errors import APIError


def _meta(extra=None):
    from .app import logical_clock
    m = {
        "api_request_id": getattr(g, "request_id", None) or new_request_id(),
        "api_request_timestamp": iso(logical_clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status: int = 200, response_type: str = "object", pagination=None):
    extra = None
    if pagination is not None:
        extra = pagination
    body = {
        "meta": _meta(extra),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def created(data, pagination=None):
    return success(data, status=201, response_type="object", pagination=pagination)


def list_ok(items, limit: int, offset: int, total: int):
    has_more = (offset + len(items)) < total
    return success(
        items,
        status=200,
        response_type="array",
        pagination={"limit": limit, "offset": offset, "total_count": total, "has_more": has_more},
    )


def error_response(e: APIError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message or e.error_id},
    }
    resp = jsonify(body)
    resp.status_code = e.status
    return resp
