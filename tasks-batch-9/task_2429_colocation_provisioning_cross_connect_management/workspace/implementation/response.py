"""Response envelope — PRD §2.2 / scaffold response_envelope.

success: { "meta": {api_request_id, api_request_timestamp}, "response_type":
          "object"|"array", "data": ... }
error:   { "meta": {...}, "response_type": "error",
           "data": {error_id, message} }
List responses additionally carry limit/offset/total_count/has_more in meta.
"""

from datetime import datetime

from flask import jsonify, request

from errors import ApiError
from util import fmt_dt, new_request_id, wall_now


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(wall_now()),
    }


def serialize(entity):
    """Public projection of a stored row: private keys (leading underscore)
    dropped, datetimes rendered ISO-8601 UTC with three fractional digits."""
    if entity is None:
        return None
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        out[key] = _plain(value)
    return out


def _plain(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


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


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# Pagination — PRD §2.3: limit defaults 10, min 1, max 100; offset defaults 0
# and may not be negative; out-of-range values are ERR_INVALID_REQUEST.
# --------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be a non-negative integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative")
    return limit, offset


def paginate(rows, limit, offset):
    """PRD §2.3 — list results sorted by created_at ascending; total_count
    counts every matching row, not merely the page."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return [serialize(r) for r in page], total
