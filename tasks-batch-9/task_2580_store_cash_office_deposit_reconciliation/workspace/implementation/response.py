"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""
import random
import string

from flask import jsonify, request

import clock
from errors import bad_request

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt(clock.wall_now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _parse_int_param(raw, name):
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("+"):
            text = text[1:]
        negative = text.startswith("-")
        digits = text[1:] if negative else text
        if not digits.isdigit():
            raise bad_request("%s must be an integer" % name)
        value = int(text)
        return value
    raise bad_request("%s must be an integer" % name)


def pagination():
    """Reads and validates limit/offset query parameters."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise bad_request("limit must be between 1 and 100")
    if raw_offset is not None:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < 0:
            raise bad_request("offset must be at least 0")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total
