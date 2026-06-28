"""Response envelope per scaffold §1.0 / PRD §2.2."""
import random
import string

from flask import jsonify

from clock import to_iso8601_millis
from datetime import datetime, timezone

# Public-facing fields per entity type (strip internal bookkeeping like _seq).
_INTERNAL = {"_seq"}


def _req_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        # request timestamp is real wall-clock (envelope metadata, not domain time)
        "api_request_timestamp": to_iso8601_millis(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def _clean(obj):
    if isinstance(obj, dict):
        return {k: v for k, v in obj.items() if k not in _INTERNAL}
    return obj


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _clean(data) if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [_clean(i) for i in items],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body
