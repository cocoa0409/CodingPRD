import random
import string
from datetime import datetime, timezone
from flask import jsonify


def iso_ms(dt):
    """ISO 8601 UTC timestamp with three fractional digits and a Z suffix
    (PRD §2.2 / §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return datetime.now(timezone.utc)


def _request_id():
    # api_request_id is a server-generated unique identifier that starts with
    # "req_" (PRD §2.2).
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alnum, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(now_dt()),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, pagination=None):
    """Standard success envelope (PRD §2.2).

    response_type is "array" for a list payload, "object" otherwise.
    Pagination fields (limit/offset/total_count/has_more) are merged into meta
    for list endpoints.
    """
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, http_status):
    """Standard error envelope (PRD §2.2). meta carries only the request id and
    timestamp; data carries error_id + message."""
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
