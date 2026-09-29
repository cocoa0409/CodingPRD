"""Response envelope exactly as PRD §2.2 / scaffold §1.0 define it:

    { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
      "response_type": "object" | "array" | "error",
      "data": {} }
"""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import fmt_dt, now

_ALNUM = string.ascii_uppercase + string.digits

# PRD §2.3 pagination contract
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """Single-resource (or empty) 2xx response — omits every pagination field."""
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(rows, page_meta):
    return (
        jsonify({"meta": _meta(page_meta), "response_type": "array", "data": rows}),
        200,
    )


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _int_param(name, raw):
    text = str(raw).strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    return value


def paginate(rows):
    """Offset pagination with the scaffold's exact parameter names and bounds."""
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        limit = _int_param("limit", args.get("limit"))
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX),
            )
    if "offset" in args:
        offset = _int_param("offset", args.get("offset"))
        if offset < OFFSET_MIN:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
