"""Response envelope and pagination helpers (PRD sections 2.2 and 2.3)."""
import random
import string

from flask import jsonify, request

from clock import now_iso
from errors import ApiError
from store import db

_ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, code=200):
    """Single-resource (or empty) 2xx envelope. Commits pending version bumps
    first so the returned representation is the post-mutation one."""
    db.commit()
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def no_content():
    db.commit()
    return "", 204


def listing(rows, limit, offset, total_count, code=200):
    db.commit()
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(rows) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), code


def error_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), _status_of(error_id)


def _status_of(error_id):
    from errors import ERROR_STATUS
    return ERROR_STATUS.get(error_id, 400)


def pagination():
    """Read and validate limit/offset. Section 2.3: out-of-range values are
    ERR_INVALID_REQUEST rather than being clamped."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def _as_int(raw):
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    try:
        return int(text)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")


def page(rows, limit, offset):
    return rows[offset:offset + limit]


def paged_listing(rows, serializer):
    """Validate pagination, apply the window and build the array envelope."""
    limit, offset = pagination()
    total = len(rows)
    window = page(rows, limit, offset)
    return listing([serializer(r) for r in window], limit, offset, total)


def array_response(rows, code=200):
    """An array payload that is not a paginated list endpoint, so meta carries no
    pagination fields (section 2.2: those are included for list endpoints)."""
    db.commit()
    body = {"meta": _meta(), "response_type": "array", "data": rows}
    return jsonify(body), code
