"""Shared helpers: time formatting, request-id generation, response envelope."""
import random
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z.

    Used for server-managed audit timestamps (created_at, updated_at) per PRD §2.4.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_sec(dt):
    """ISO 8601 UTC at second granularity (no fractional digits) with trailing Z.

    Used for computed instants (deadlines, dig-window boundaries, mark-out
    validity, dispatch/completion stamps) per PRD §2.9.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    """Parse an ISO 8601 UTC instant into an aware datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _meta(request_id, timestamp, pagination=None):
    meta = {
        "api_request_id": request_id,
        "api_request_timestamp": iso_ms(timestamp),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, request_id, timestamp, status=200, is_array=False, pagination=None):
    body = {
        "meta": _meta(request_id, timestamp, pagination),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, request_id, timestamp, status):
    body = {
        "meta": _meta(request_id, timestamp),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
