"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import g, jsonify, request

from errors import api_error
from timeutil import fmt_iso, wall_now

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def gen_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": getattr(g, "request_id", None) or gen_request_id(),
        "api_request_timestamp": fmt_iso(wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data or {}}), status


def array_response(items, limit, offset, total_count):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return jsonify({"meta": _meta(meta), "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _as_int(raw, field):
    if isinstance(raw, str):
        candidate = raw.strip()
        if candidate.startswith("+"):
            candidate = candidate[1:]
        negative = candidate.startswith("-")
        digits = candidate[1:] if negative else candidate
        if digits.isdigit():
            return -int(digits) if negative else int(digits)
    raise api_error("ERR_INVALID_REQUEST", "%s must be an integer." % field)


def pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in request.args:
        limit = _as_int(request.args.get("limit"), "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise api_error(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
            )
    if "offset" in request.args:
        offset = _as_int(request.args.get("offset"), "offset")
        if offset < 0:
            raise api_error("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(items, serializer):
    limit, offset = pagination()
    total = len(items)
    page = items[offset : offset + limit]
    return array_response([serializer(item) for item in page], limit, offset, total)
