"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify

from db import iso, wall_now
from errors import ApiError

_ALPHABET = string.ascii_lowercase + string.digits

# SCAFFOLD response_envelope.pagination_defaults
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total,
                "has_more": offset + len(page) < total,
            }
        ),
        "response_type": "array",
        "data": [serializer(r) for r in page],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _int_param(raw, name):
    if isinstance(raw, str):
        raw = raw.strip()
    if raw is None or raw == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    try:
        return int(raw, 10) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)


def pagination(args):
    """PRD 2.3: offset pagination with limit 1..100 (default 10) and offset >= 0."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        limit = _int_param(args.get("limit"), "limit")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX),
            )
    if "offset" in args:
        offset = _int_param(args.get("offset"), "offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be non-negative")
    return limit, offset
