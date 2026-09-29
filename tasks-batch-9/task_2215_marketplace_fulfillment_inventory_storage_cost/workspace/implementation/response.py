"""Response envelope helpers (PRD §2.2, §2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page_params(args):
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    limit = PAGE_LIMIT_DEFAULT
    raw = args.get("limit")
    if raw is not None and str(raw).strip() != "":
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            limit = PAGE_LIMIT_DEFAULT
        limit = max(PAGE_LIMIT_MIN, min(PAGE_LIMIT_MAX, limit))
    offset = PAGE_OFFSET_DEFAULT
    raw = args.get("offset")
    if raw is not None and str(raw).strip() != "":
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            offset = PAGE_OFFSET_DEFAULT
        offset = max(0, offset)
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
