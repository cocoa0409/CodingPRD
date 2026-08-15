"""Standard response envelope helpers."""
import uuid
from datetime import datetime, timezone
from flask import jsonify

import db


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def _meta(pagination=None):
    m = {
        "api_request_id": f"req_{uuid.uuid4().hex[:20]}",
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_err.error_id,
            "message": api_err.message,
        },
    }
    return jsonify(body), api_err.http_status
