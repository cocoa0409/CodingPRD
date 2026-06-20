"""Standard response-envelope helpers.

Success: { meta:{api_request_id, api_request_timestamp, [pagination]},
           response_type:"object"|"array", data:{} }
Error:   { meta:{api_request_id, api_request_timestamp},
           response_type:"error", data:{error_id, message} }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def list_success(items, limit, offset, total_count, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return success(items, status=status, response_type="array", pagination=pagination)


def error(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
