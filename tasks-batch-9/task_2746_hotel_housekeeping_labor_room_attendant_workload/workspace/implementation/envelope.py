"""Response envelope helpers -- PRD 2.2 and SCAFFOLD response_envelope.

success: { "meta": { "api_request_id", "api_request_timestamp"[, pagination] },
           "response_type": "object" | "array", "data": ... }
error:   { "meta": { "api_request_id", "api_request_timestamp" },
           "response_type": "error",
           "data": { "error_id", "message" } }
"""

from flask import jsonify

from store import STORE, new_request_id, sorted_rows
from timeutil import format_iso_datetime
from errors import ApiError


PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_iso_datetime(STORE.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
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


def read_pagination(args):
    """PRD 2.3: limit defaults to 10, minimum 1, maximum 100; offset defaults to 0."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset))
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(rows, args, serializer):
    """Filter-then-paginate: total_count reflects the filtered set (PRD 2.3)."""
    limit, offset = read_pagination(args)
    ordered = sorted_rows(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)


def filtered(rows, args, mapping):
    """Apply the endpoint's declared filters, combined with logical conjunction and
    applied BEFORE pagination so total_count reflects the filtered set (PRD 2.3).

    `mapping` maps a query parameter name to (row key, renderer) where the renderer
    turns the stored value into the string form the caller would have supplied.
    """
    out = []
    for row in rows:
        keep = True
        for param, spec in mapping.items():
            raw = args.get(param)
            if raw is None or raw == "":
                continue
            key, render = spec
            value = row.get(key)
            value = render(value) if render is not None else value
            if value != raw:
                keep = False
                break
        if keep:
            out.append(row)
    return out
