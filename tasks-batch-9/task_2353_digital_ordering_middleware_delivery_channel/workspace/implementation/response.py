"""Standard response envelope (PRD 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_uppercase + string.digits


def _api_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _api_request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta(extra=None):
    meta = {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": _api_request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def array_response(data, pagination, status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(records, limit, offset):
    """Slice a sorted record list and build the pagination meta block."""
    total = len(records)
    page = records[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
