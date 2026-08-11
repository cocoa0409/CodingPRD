import json

from flask import jsonify, request

import db
from errors import raise_err
from utils import new_request_id, iso


def _meta(pagination=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(db.now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err("ERR_VALIDATION", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: full sorted list. Returns (page, pagination_meta)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def get_body():
    if not request.data:
        return {}
    try:
        body = json.loads(request.data)
    except Exception:
        raise_err("ERR_VALIDATION", "request body is not valid JSON")
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "request body must be a JSON object")
    return body


def no_body_fields():
    """For endpoints with no declared inputs: any body field is unknown."""
    body = get_body()
    if body:
        raise_err("ERR_VALIDATION", f"unknown field: {sorted(body)[0]}")
