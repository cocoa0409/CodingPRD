"""Standard response envelope per PRD §2.2 / §2.3.

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""

import secrets
import string
from datetime import datetime

from flask import jsonify, request

import clock

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt(clock.now()),
    }


def serialize(rec):
    """Public view of a record: drop internal `_` fields, render datetimes."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = clock.fmt(v)
        else:
            out[k] = v
    return out


def ok(data, status=200):
    """Single-resource (or free-form object) success envelope."""
    if isinstance(data, dict) and "_seq" in data:
        data = serialize(data)
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    """List envelope with pagination fields in meta."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in items],
    }
    return jsonify(body), 200


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    """limit defaults 10, clamped to [1, 100]; offset defaults 0, floored at 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(records):
    """Sort by created_at ascending (insertion order breaks same-instant ties),
    then paginate and wrap."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list(page, total, limit, offset)
