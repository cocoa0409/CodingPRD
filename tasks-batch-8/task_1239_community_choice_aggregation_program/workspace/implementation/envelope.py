"""Response envelope helpers (PRD §2.2 / §2.3)."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST
from util import fmt_dt

_ALNUM = string.ascii_letters + string.digits


def _req_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def ok_object(data, status=200):
    return ok(data, status=status, response_type="object")


def ok_list(items, status=200, pagination=None):
    return ok(items, status=status, response_type="array",
              pagination=pagination if pagination is not None else
              {"limit": len(items), "offset": 0, "total_count": len(items),
               "has_more": False})


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    """Parse limit/offset query params per scaffold defaults: limit 10 (1..100), offset 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, serializer):
    """records: pre-sorted list. Returns a Flask response with list envelope."""
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return ok_list([serializer(r) for r in page], pagination=pagination)


def sorted_records(coll):
    """Default list ordering: created_at ascending (stable via internal seq)."""
    return sorted(coll.values(), key=lambda r: (r.get("_created_dt"), r.get("_seq", 0)))
