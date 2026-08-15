"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import uuid
from datetime import datetime

from flask import jsonify, request

from errors import ApiError, err_validation
from store import now
from timeutil import iso


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": iso(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0 (min 0).
    Out-of-range values are clamped; unparseable values fall back to defaults."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(100, limit))
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)
    return limit, offset
