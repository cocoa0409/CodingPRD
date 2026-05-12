"""Standard response envelope."""
import datetime
import secrets
import string
from flask import jsonify


def _gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _timestamp_iso() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    # ISO 8601 UTC, 3 fractional digits, ending Z
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, status: int = 200, response_type: str = "object", pagination: dict = None):
    meta = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _timestamp_iso(),
    }
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id: str, message: str, status: int):
    meta = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _timestamp_iso(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status


def parse_pagination(args) -> tuple:
    """Parse limit and offset from request.args. Returns (limit, offset)."""
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


def paginate(items: list, limit: int, offset: int) -> tuple:
    """Slice items, return (slice, pagination_meta)."""
    total = len(items)
    sliced = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return sliced, pag


def list_response(items: list, limit: int, offset: int, status: int = 200):
    """Build a paginated list response."""
    sliced, pag = paginate(items, limit, offset)
    return success(sliced, status=status, response_type="array", pagination=pag)
