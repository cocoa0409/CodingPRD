"""Standard response envelope helpers."""
import uuid
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _meta(with_pagination=None):
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(now.microsecond // 1000)
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": ts,
    }
    if with_pagination:
        meta.update(with_pagination)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def ok_list(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), 200


def error_response(err):
    if isinstance(err, ApiError):
        status = err.http_status
        data = {"error_id": err.error_id, "message": err.message}
    else:
        status = 500
        data = {"error_id": "ERR_INTERNAL", "message": str(err)}
    body = {"meta": _meta(), "response_type": "error", "data": data}
    return jsonify(body), status
