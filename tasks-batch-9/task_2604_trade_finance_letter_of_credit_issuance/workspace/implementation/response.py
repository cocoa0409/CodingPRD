"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from db import wall_now_iso
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _api_request_id(), "api_request_timestamp": wall_now_iso()}


def ok(data=None, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data=None):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error", "data": {"error_id": error_id, "message": message}}


def error_response(exc):
    return jsonify(error_body(exc.error_id, exc.message)), exc.http_status


def _parse_page_int(raw, field):
    if isinstance(raw, str):
        raw = raw.strip()
    if raw is None or raw == "":
        return None
    try:
        return int(raw, 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % field)


def page_params():
    limit = _parse_page_int(request.args.get("limit"), "limit")
    offset = _parse_page_int(request.args.get("offset"), "offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_REQUEST", "limit is out of range")
    if offset < PAGINATION_DEFAULT_OFFSET:
        raise ApiError("ERR_INVALID_REQUEST", "offset is out of range")
    return limit, offset


def paginated(rows, serializer):
    """rows must already be in the endpoint's declared order."""
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
