"""Response envelope helpers (PRD §2.2 / SCAFFOLD §1.0).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": ISO8601,
              [limit/offset/total_count/has_more for lists] },
    "response_type": "object"|"array", "data": ... }
Error:
  { "meta": { api_request_id, api_request_timestamp },
    "response_type": "error", "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime, timezone
from flask import jsonify

from timeutil import now_iso

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def empty_response(status=200):
    return success({}, status=status, response_type="object")


def array_response(items, limit, offset, total_count):
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
    return jsonify(body), status
