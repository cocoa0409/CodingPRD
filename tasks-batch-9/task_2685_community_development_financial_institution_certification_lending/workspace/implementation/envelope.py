"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail
from store import public, request_id

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    stamp = datetime.now(timezone.utc)
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": stamp.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (stamp.microsecond // 1000),
    }


def ok(row, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": public(row) if row is not None else {},
    }
    return jsonify(body), status


def created(row):
    return ok(row, 201)


def empty(status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": {}}), status


def page(rows, limit, offset, status=200):
    total = len(rows)
    window = rows[offset: offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in window],
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination():
    """Read and validate `limit`/`offset` (PRD 2.3)."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail("ERR_INVALID_PAGINATION")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION")
        if offset < PAGE_OFFSET_DEFAULT:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def qs(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qs_bool(name):
    value = qs(name)
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None
