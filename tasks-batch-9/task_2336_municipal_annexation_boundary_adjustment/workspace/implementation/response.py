"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string
from datetime import date, datetime
from decimal import Decimal

from flask import jsonify, request

from clockutil import iso3, wall_now
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": iso3(wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def serialize(value):
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return iso3(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data if data is not None else {}),
    }
    return jsonify(body), status


def list_response(items, limit, offset, total_count):
    page = items
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + len(page) < total_count,
            }
        ),
        "response_type": "array",
        "data": serialize(page),
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination():
    """limit / offset from the query string, validated per PRD §2.3."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_INVALID", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_PAGINATION_INVALID", "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_INVALID", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_PAGINATION_INVALID", "offset may not be negative.")
    return limit, offset


def paginate(records, filters=None):
    """Apply equality filters from the query string, then paginate."""
    limit, offset = pagination()
    rows = records
    if filters:
        for field in filters:
            wanted = request.args.get(field)
            if wanted is not None and wanted != "":
                rows = [r for r in rows if str(r.get(field)) == wanted]
    total = len(rows)
    return list_response(rows[offset: offset + limit], limit, offset, total)
