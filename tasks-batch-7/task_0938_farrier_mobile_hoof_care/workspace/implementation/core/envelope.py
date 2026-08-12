"""The response envelope of PRD 2.2 and the pagination rules of PRD 2.3."""

from flask import jsonify, request

from . import ids
from .constants import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, MIN_PAGE_LIMIT
from .errors import ApiError
from .timeutil import clock


def _meta():
    return {
        "api_request_id": ids.new_request_id(),
        "api_request_timestamp": clock.instant(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(rows, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_pagination():
    """Read and range-check ``limit`` and ``offset`` (rung 23)."""
    limit = DEFAULT_PAGE_LIMIT
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALUE_OUT_OF_RANGE", "limit must be an integer.")
        if limit < MIN_PAGE_LIMIT or limit > MAX_PAGE_LIMIT:
            raise ApiError(
                "ERR_VALUE_OUT_OF_RANGE",
                "limit must be between %d and %d inclusive." % (MIN_PAGE_LIMIT, MAX_PAGE_LIMIT),
            )
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALUE_OUT_OF_RANGE", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALUE_OUT_OF_RANGE", "offset may not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total


def apply_filters(rows, spec):
    """Exact-match conjunctive filters (PRD 2.3).

    ``spec`` maps a query-parameter name to the row field it narrows.  A filter
    value that matches no row is not an error: it simply yields an empty page.
    """
    out = rows
    for param, field in spec.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [r for r in out if _as_text(r.get(field)) == raw]
    return out


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
