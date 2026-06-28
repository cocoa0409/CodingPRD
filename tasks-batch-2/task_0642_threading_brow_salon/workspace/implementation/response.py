"""Response envelope helpers (PRD §2.2) and entity serializers.

Success envelope:
  { "meta": { "api_request_id", "api_request_timestamp", <pagination?> },
    "response_type": "object" | "array", "data": {...} | [...] }
Error envelope:
  { "meta": { "api_request_id", "api_request_timestamp" },
    "response_type": "error", "data": { "error_id", "message" } }
"""
import random
import string
from datetime import datetime

from flask import jsonify

import clock

# Fields on each stored entity that are tz-aware datetimes needing ISO rendering.
_DATETIME_FIELDS = {
    "created_at", "updated_at",
    "license_expiry", "sanitation_cert_expiry", "sanitation_ready_at",
    "joined_at", "seated_at", "ended_at",
}

# Internal bookkeeping keys never exposed in responses.
_INTERNAL = {"_seq"}


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphanum) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.to_iso8601(clock.now()),
    }
    if extra:
        m.update(extra)
    return m


def serialize(obj):
    """Render a stored entity dict for transport: ISO-render datetimes, drop internals."""
    if obj is None:
        return None
    out = {}
    for k, v in obj.items():
        if k in _INTERNAL:
            continue
        if k in _DATETIME_FIELDS:
            out[k] = clock.to_iso8601(v) if isinstance(v, datetime) else v
        else:
            out[k] = v
    return out


def ok(data, status=200, response_type="object"):
    body = {
        "meta": _meta(),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def object_response(obj, status=200):
    return ok(serialize(obj), status=status, response_type="object")


def list_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": [serialize(o) for o in items],
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
