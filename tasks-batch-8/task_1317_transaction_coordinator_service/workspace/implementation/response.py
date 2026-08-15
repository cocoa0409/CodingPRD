"""Standard response envelope helpers (PRD section 2.2)."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(22))


def _wall_ts():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def ok_object(data, status=200):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _wall_ts()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_ts(),
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _wall_ts()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
