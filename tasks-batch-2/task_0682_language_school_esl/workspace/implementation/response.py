"""Standard response envelope (PRD §2.2)."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify

from clock import iso_millis


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _wall_now_iso():
    # api_request_timestamp is a real (wall-clock) server timestamp, distinct from
    # the logical clock used for business calculations (PRD §2.4).
    return iso_millis(datetime.now(timezone.utc))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_now_iso(),
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
    return jsonify(body), status


def list_response(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
