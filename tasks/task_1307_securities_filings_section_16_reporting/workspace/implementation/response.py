"""Standard response envelope helpers (PRD §2.2)."""
import random
import string
from flask import jsonify

from db import db


def _now_iso():
    """Logical clock timestamp with 3 fractional digits, Z suffix."""
    raw = db.clock
    if raw.endswith("Z"):
        raw = raw[:-1]
    if "." in raw:
        head, tail = raw.split(".", 1)
        tail = (tail + "000")[:3]
        return f"{head}.{tail}Z"
    return raw + ".000Z"


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
