"""Response envelope helpers."""
import datetime
import secrets
import string

from flask import jsonify


def _alnum(n):
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(n))


def request_id() -> str:
    return "req_" + _alnum(20)


def now_iso_z() -> str:
    """ISO 8601 UTC, milliseconds precision, 'Z' suffix."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def make_meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso_z(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, http_status=200, response_type="object", pagination=None):
    meta = make_meta(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def list_success(items, limit, offset, total_count, http_status=200):
    has_more = offset + limit < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, http_status=http_status, response_type="array", pagination=pagination)


def error_response(error_id: str, message: str, http_status: int):
    meta = make_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
