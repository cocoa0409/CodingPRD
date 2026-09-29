"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify, request

from db import wall_now_iso
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }


def clean(value):
    """Strip internal keys and normalise types for JSON output."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def ok(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": clean(data),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": clean(rows),
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def read_pagination():
    """Parse limit/offset; PRD 2.3.  Out-of-range -> ERR_INVALID_PAGINATION."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        limit = _as_int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        offset = _as_int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be 0 or greater")
    return limit, offset


def _as_int(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION", "pagination parameters must be integers")


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
