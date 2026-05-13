"""Standard response envelope helpers."""
import random
import string
from flask import jsonify

from clock import clock, iso


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _meta(pagination=None) -> dict:
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(clock.now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, status: int = 200, pagination=None, response_type=None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination=pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error(error_id: str, message: str, status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def paginate(items: list, limit: int, offset: int):
    """Return slice + pagination meta."""
    total = len(items)
    start = max(0, offset)
    end = start + limit
    page = items[start:end]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": end < total,
    }
    return page, meta


def parse_pagination(args):
    """Read limit/offset from query args with defaults & bounds."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
