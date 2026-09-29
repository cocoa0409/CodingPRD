"""Standard response envelope and offset pagination (PRD §2.2, §2.3)."""
import json
import re
from decimal import Decimal

from flask import Response, request

import db
from errors import ApiError

_INT_RE = re.compile(r"^[+-]?\d+$")


def _meta(extra=None):
    meta = {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.wall_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def serialize(value):
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [serialize(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json(payload, status):
    return Response(json.dumps(payload), status=status, mimetype="application/json")


def ok(data, status=200):
    return _json({"meta": _meta(), "response_type": "object", "data": serialize(data)}, status)


def created(data):
    return ok(data, 201)


def collection(rows, page_meta):
    payload = {
        "meta": _meta(page_meta),
        "response_type": "array",
        "data": serialize(rows),
    }
    return _json(payload, 200)


def error(exc):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return _json(payload, exc.status)


def _int_param(raw, name):
    if isinstance(raw, str):
        raw = raw.strip()
    if not raw or not _INT_RE.match(raw):
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    return int(raw)


def pagination_params():
    """PRD §2.3 — limit defaults 10 in [1, 100]; offset defaults 0, non-negative."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _int_param(raw_limit, "limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _int_param(raw_offset, "offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must not be negative")
    return limit, offset


def paginate(rows):
    """Sort by created_at ascending, slice the window, and build the meta block."""
    limit, offset = pagination_params()
    rows = db.sort_rows(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def listing(rows):
    page, meta = paginate(rows)
    return collection(page, meta)


def filter_rows(rows, *fields):
    """Apply the declared query-parameter filters by exact string match."""
    out = rows
    for field in fields:
        raw = request.args.get(field)
        if raw is None:
            continue
        out = [r for r in out if r.get(field) is not None and str(r.get(field)) == raw]
    return out
