"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

import db


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z",
    }


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp
