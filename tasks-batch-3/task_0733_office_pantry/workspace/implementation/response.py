"""Response envelope helpers per PRD §2.2."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _now_iso() -> str:
    # ISO 8601 UTC, three fractional digits, 'Z' suffix
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    tail = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{tail}"


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def created(data):
    return ok(data, status=201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = int(limit)
    meta["offset"] = int(offset)
    meta["total_count"] = int(total_count)
    meta["has_more"] = (int(offset) + int(limit)) < int(total_count)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
