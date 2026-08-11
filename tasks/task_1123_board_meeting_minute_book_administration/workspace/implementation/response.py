"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import uuid
from datetime import datetime

from flask import jsonify

from errors import ERR_VALIDATION, raise_err
from util import iso_ms, wall_now_iso_ms


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_now_iso_ms(),
    }


def serialize_value(value):
    if isinstance(value, datetime):
        return iso_ms(value)
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    return value


def serialize_row(row):
    """Public view of a stored row: drops internal fields, renders
    datetimes as ISO strings."""
    return {
        key: serialize_value(value)
        for key, value in row.items()
        if not key.startswith("_")
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(rows, limit, offset, total_count, extra_meta=None):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    if extra_meta:
        meta.update(extra_meta)
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """limit: default 10, accepted range 1..100. offset: default 0, >= 0."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "Query parameter 'limit' must be an integer")
        if str(limit_raw).strip() != str(limit):
            raise_err(ERR_VALIDATION, "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "Query parameter 'limit' must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "Query parameter 'offset' must be an integer")
        if str(offset_raw).strip() != str(offset):
            raise_err(ERR_VALIDATION, "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "Query parameter 'offset' must be >= 0")
    return limit, offset


def list_response(store_rows, filters, args, sort_key=None):
    """Apply equality filters, sort (default created_at asc with insertion
    order tie-break), paginate, and wrap in the list envelope."""
    rows = list(store_rows)
    for field, wanted in filters:
        if wanted is None:
            continue
        rows = [r for r in rows if _filter_value(r.get(field)) == wanted]
    if sort_key is None:
        rows.sort(key=lambda r: (r.get("created_at"), r.get("_seq", 0)))
    else:
        rows.sort(key=sort_key)
    total = len(rows)
    limit, offset = parse_pagination(args)
    page = rows[offset:offset + limit]
    return success_list([serialize_row(r) for r in page], limit, offset, total)


def _filter_value(value):
    if isinstance(value, datetime):
        return iso_ms(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return str(value) if not isinstance(value, (int, float)) else value
