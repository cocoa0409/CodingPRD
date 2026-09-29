"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

import clock
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": clock.iso(clock.now()),
    }


def object_body(data):
    return {"meta": base_meta(), "response_type": "object", "data": data}


def array_body(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def send(body, status):
    return jsonify(body), status


def read_pagination(args):
    """Parse and validate limit/offset query parameters."""
    limit = DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        limit = _positive_int(args.get("limit"))
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (MIN_LIMIT, MAX_LIMIT),
            )
    if "offset" in args:
        offset = _positive_int(args.get("offset"))
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def _positive_int(raw):
    if raw is None:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    text = str(raw).strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    try:
        return int(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
