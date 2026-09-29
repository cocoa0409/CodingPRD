"""Response envelope helpers (PRD 2.2) and offset/limit pagination (PRD 2.3)."""
import re

from flask import jsonify, request

from errors import ApiError
from util import new_request_id, real_now_iso

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0

_INT_RE = re.compile(r"^[+-]?[0-9]+$")


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": real_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_pagination():
    """Validate limit/offset. Raises ERR_INVALID_PAGINATION (400)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            raise ApiError("ERR_INVALID_PAGINATION")
        limit = int(raw_limit.strip())
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset.strip()):
            raise ApiError("ERR_INVALID_PAGINATION")
        offset = int(raw_offset.strip())
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginated(rows, serializer):
    """Apply limit/offset to an already-sorted row list and build the envelope."""
    limit, offset = read_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok([serializer(r) for r in page], 200, meta_extra)
