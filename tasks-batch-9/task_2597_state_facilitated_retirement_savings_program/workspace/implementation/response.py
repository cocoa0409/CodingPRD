"""Response envelope helpers (PRD 2.2) and offset pagination (PRD 2.3)."""
from flask import jsonify, request

from errors import ApiError, fail
from store import db
from util import new_request_id

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def single(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return single(data, 201)


def collection(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ------------------------------------------------------------------ paging

def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    return value


def pagination():
    limit = _int_param("limit", DEFAULT_LIMIT)
    offset = _int_param("offset", DEFAULT_OFFSET)
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return collection([serializer(row) for row in page], limit, offset, total)


def query_filter(name, allowed=None):
    """Read one optional query filter; validate enum membership when declared."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if allowed is not None and raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s has an unknown value" % name)
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = raw.strip()
    digits = text[1:] if text.startswith("-") else text
    if not digits.isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return int(text)


__all__ = [
    "single", "created", "collection", "error_response", "paginate",
    "pagination", "query_filter", "query_bool", "query_int", "ApiError",
]
