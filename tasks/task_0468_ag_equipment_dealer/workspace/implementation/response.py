"""Response envelope helpers (PRD §2.2). Field names taken verbatim from the
scaffold response_envelope: meta / api_request_id / api_request_timestamp /
response_type / data, plus pagination fields limit/offset/total_count/has_more.
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from clock import format_iso8601_ms


def _request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        # api_request_timestamp is server wall-clock (the moment of the response),
        # ISO 8601 UTC with three fractional digits — independent of the logical clock.
        "api_request_timestamp": format_iso8601_ms(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


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
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp
