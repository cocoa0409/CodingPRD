"""Response envelope helpers (PRD §2.2)."""
import random
import string
from datetime import timezone

from flask import jsonify

from clock import now as logical_now
import realclock


def _req_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso_ts(dt):
    """ISO 8601 UTC with exactly 3 fractional digits, trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    # api_request_timestamp is a server-generated wall-clock instant, distinct
    # from the logical clock used for business time.
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": iso_ts(realclock.wall_now()),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_array(items, limit, offset, total_count, status=200):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
