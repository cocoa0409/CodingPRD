"""Standard response envelope helpers."""

import secrets
import string
from datetime import datetime, timezone
from flask import jsonify

from clock import clock


def _format_iso(dt: datetime) -> str:
    # ISO 8601 UTC with three fractional digits, ending 'Z'.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def _gen_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta_base():
    return {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _format_iso(clock.now()),
    }


def success_response(data, status_code=200, response_type="object", pagination=None):
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status_code
    return resp


def list_response(items, total_count, limit, offset, status_code=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return success_response(items, status_code=status_code, response_type="array", pagination=pagination)


def error_response(error_id: str, message: str, http_status: int):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def format_iso(dt: datetime) -> str:
    return _format_iso(dt)
