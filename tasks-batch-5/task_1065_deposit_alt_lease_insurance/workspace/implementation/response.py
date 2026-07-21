"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope)."""
import random
import string
from flask import jsonify
from db import now, fmt_ts

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    alnum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }


def object_response(data, http_status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def array_response(items, http_status=200, limit=None, offset=None, total_count=None):
    meta = _base_meta()
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params, clamping/validating per PRD §2.3."""
    from errors import err

    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err("ERR_VALIDATION", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    items_sorted = sorted(items, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))
    total_count = len(items_sorted)
    window = items_sorted[offset:offset + limit]
    return window, total_count
