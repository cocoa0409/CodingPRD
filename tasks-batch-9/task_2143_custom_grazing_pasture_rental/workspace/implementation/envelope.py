"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import now_iso

ALNUM = string.ascii_uppercase + string.digits

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination():
    """Validate + return (limit, offset).  Priority 6 -> ERR_INVALID_PAGINATION."""
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit is None or limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer no smaller than 0.")
    return limit, offset


def _as_int(raw):
    raw = raw.strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def public(record):
    """Serialize a stored record, dropping internal bookkeeping keys."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def public_list(records):
    return [public(r) for r in records]
