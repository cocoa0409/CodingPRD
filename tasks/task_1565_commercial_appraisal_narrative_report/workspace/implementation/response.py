import json
import secrets

from flask import Response, request

from db import store, fmt_dt
from errors import ApiError, ERR_INVALID_REQUEST


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": fmt_dt(store.clock),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return Response(json.dumps(body), status=status, mimetype="application/json")


def list_response(items):
    page, pagination = paginate(items)
    return success(page, status=200, response_type="array", pagination=pagination)


def error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(json.dumps(body), status=status, mimetype="application/json")


def paginate(items):
    """limit/offset pagination per the scaffold envelope: default limit 10,
    min 1, max 100, default offset 0; meta carries limit/offset/total_count/has_more."""
    args = request.args
    total = len(items)
    limit, offset = 10, 0
    raw = args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    raw = args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def sort_by_creation(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
