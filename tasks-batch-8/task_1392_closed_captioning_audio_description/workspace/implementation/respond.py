"""Standard response envelope (PRD §2.2) and pagination (PRD §2.3)."""
import uuid

from flask import jsonify, request

from db import now
from errors import ApiError, ERR_VALIDATION
from util import fmt_dt


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """limit defaults to 10, min 1, max 100; offset defaults to 0 (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "Query parameter 'limit' must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "Query parameter 'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(ERR_VALIDATION, 400, "Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise ApiError(ERR_VALIDATION, 400, "Query parameter 'offset' must be >= 0")
    return limit, offset


def list_response(records, serialize):
    """Sort by created_at ascending (insertion order breaks ties), filter and
    paginate. `records` is an iterable of internal record dicts."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


def filter_eq(records, field, value):
    if value is None:
        return [r for r in records]
    return [r for r in records if r.get(field) == value]
