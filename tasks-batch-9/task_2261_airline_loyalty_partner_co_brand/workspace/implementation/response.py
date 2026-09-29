"""Response envelope helpers -- PRD 2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_uppercase + string.digits


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    return iso_ms(datetime.now(timezone.utc))


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    m = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return jsonify({
        "meta": m,
        "response_type": "array",
        "data": items,
    }), 200


def error_body(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
