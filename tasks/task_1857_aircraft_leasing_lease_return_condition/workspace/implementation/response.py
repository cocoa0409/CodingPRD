"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string

from flask import jsonify, request

from db import now_iso
from errors import bad_request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": response_type,
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_envelope(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad_request("Query parameter %s must be an integer" % name)


def paginated(items):
    """Apply limit/offset query params and wrap in the list envelope."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = DEFAULT_LIMIT if raw_limit is None else _parse_int_param(raw_limit, "limit")
    offset = DEFAULT_OFFSET if raw_offset is None else _parse_int_param(raw_offset, "offset")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise bad_request("limit must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT))
    if offset < 0:
        raise bad_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return success(
        page,
        response_type="array",
        status=200,
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        },
    )
