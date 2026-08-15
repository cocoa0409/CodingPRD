"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""
import random
import string

from flask import jsonify

import store
from errors import ApiError, ERR_INVALID_REQUEST, raise_err


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Read limit/offset query params with defaults/min/max from the scaffold."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) or limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if str(raw_offset).strip() != str(offset) or offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be a non-negative integer")
    return limit, offset


def paginate(records, args):
    """Sort by created_at ASC (insertion order tiebreak), filter applied by caller."""
    limit, offset = parse_pagination(args)
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def sort_records(records):
    return sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
