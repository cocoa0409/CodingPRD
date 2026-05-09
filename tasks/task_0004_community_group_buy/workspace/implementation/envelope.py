"""Response envelope helpers (PRD §2.2)."""
import random
import string
import time
from datetime import datetime, timezone

from flask import jsonify


_last_ts_us = [0]


def iso_now():
    """ISO 8601 UTC with three fractional digits, monotonically increasing."""
    now_us = int(time.time() * 1_000_000)
    if now_us <= _last_ts_us[0]:
        now_us = _last_ts_us[0] + 1000
    _last_ts_us[0] = now_us
    secs, us = divmod(now_us, 1_000_000)
    dt = datetime.fromtimestamp(secs, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{us // 1000:03d}Z"


def new_request_id():
    chars = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


def _meta(extra=None):
    m = {"api_request_id": new_request_id(), "api_request_timestamp": iso_now()}
    if extra:
        m.update(extra)
    return m


def success(data, http_status=200, response_type="object", pagination=None):
    payload = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(payload), http_status


def list_success(items, total, limit, offset, http_status=200):
    return success(
        items,
        http_status=http_status,
        response_type="array",
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + limit < total,
        },
    )


def error(error_id, http_status, message=None):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(payload), http_status
