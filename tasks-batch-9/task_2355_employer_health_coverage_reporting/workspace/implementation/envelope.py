"""Response envelope, pagination and list serialisation (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

from db import now_iso, serialize
from errors import ApiError, fail

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def _sync_if_mutating():
    """Refresh every derived counter before a mutating response is rendered."""
    if request.method in ("POST", "PATCH", "PUT", "DELETE"):
        import sync

        sync.sync_all()


def ok(data, status=200):
    _sync_if_mutating()
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data) if isinstance(data, dict) else data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_raw(data, status=200):
    """Success envelope for a payload that is not a stored entity."""
    _sync_if_mutating()
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def collection(rows, status=200):
    """Paginated list envelope; `rows` must already be ordered."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in page],
    }
    return jsonify(body), status


def created_collection(rows):
    """201 envelope for the atomic batch creates, which return an array."""
    _sync_if_mutating()
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 201


def pagination():
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.status


def filtered(rows, spec):
    """Apply the declared query-parameter filters of a list endpoint.

    `spec` maps a query parameter name to (record field, kind) where kind is
    one of "str", "int" or "bool".  A numeric filter that cannot be parsed
    simply matches nothing.
    """
    out = rows
    for param, (field, kind) in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "int":
            try:
                value = int(raw)
            except (TypeError, ValueError):
                return []
        elif kind == "bool":
            lowered = raw.strip().lower()
            if lowered in ("true", "1"):
                value = True
            elif lowered in ("false", "0"):
                value = False
            else:
                return []
        else:
            value = raw
        out = [r for r in out if r.get(field) == value]
    return out


__all__ = [
    "ok",
    "created",
    "ok_raw",
    "collection",
    "created_collection",
    "error_response",
    "filtered",
    "ApiError",
]
