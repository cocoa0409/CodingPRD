"""Response envelope helpers (PRD 2.2 / 2.3, SCAFFOLD response_envelope)."""

import random
import string

from flask import jsonify, request

from db import db, format_instant, public
from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_str(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty(status=200):
    return ok({}, status)


def page_params():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = int(limit) if limit is not None and str(limit).strip() != "" else LIMIT_DEFAULT
    except (TypeError, ValueError):
        limit = LIMIT_DEFAULT
    try:
        offset = int(offset) if offset is not None and str(offset).strip() != "" else OFFSET_DEFAULT
    except (TypeError, ValueError):
        offset = OFFSET_DEFAULT
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < OFFSET_MIN:
        offset = OFFSET_MIN
    return limit, offset


def listing(rows):
    """Paginate rows (already ordered) and render the list envelope."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in window],
    }
    return jsonify(body), 200


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def render_error(exc):
    if isinstance(exc, ApiError):
        return error_body(exc.error_id, exc.message, exc.http_status)
    return error_body("ERR_INVALID_REQUEST", str(exc), 400)
