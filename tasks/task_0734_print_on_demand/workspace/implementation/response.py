"""Response envelope helpers per PRD §2.2."""
import random
import string
from flask import jsonify, request

from clock import clock


def _req_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def created(data):
    return ok(data, status=201)


def paginated(items, total_count, limit, offset):
    has_more = (offset + limit) < total_count
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": has_more,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def parse_pagination():
    """Parse and validate ?limit=&offset= from the current request. Defaults from PRD §2.3."""
    from errors import raise_error

    args = request.args
    limit = args.get("limit", 10)
    offset = args.get("offset", 0)
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        raise_error("ERR_INVALID_REQUEST", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_error("ERR_INVALID_REQUEST", "limit must be in [1,100]")
    if offset < 0:
        raise_error("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate_and_serialize(rows, serializer):
    """Apply pagination and serialize. Rows arrive already sorted by (created_at, insertion_seq)."""
    limit, offset = parse_pagination()
    total = len(rows)
    slc = rows[offset : offset + limit]
    return paginated([serializer(r) for r in slc], total, limit, offset)
