"""Response envelope helpers (PRD §2.2 / scaffold §1.0).

Success: {"meta": {"api_request_id", "api_request_timestamp"}, "response_type": "object"|"array", "data": ...}
List responses add limit/offset/total_count/has_more to meta.
Error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def _wall_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def success(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status
