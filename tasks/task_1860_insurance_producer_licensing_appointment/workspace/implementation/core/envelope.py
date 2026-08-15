"""The response envelope of PRD section 2.2 and the pagination of section 2.3."""

import random
import string

from flask import jsonify, request

from . import constants as K
from .clock import render_instant
from .store import db

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        # api_request_timestamp is server-written off the logical clock,
        # three fractional digits, trailing Z (PRD 2.2 / 2.5).
        "api_request_timestamp": render_instant(db.now),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _clamp_int(raw, default, minimum, maximum):
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    if value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def pagination():
    """PRD 2.3: limit defaults 10 (min 1, max 100); offset defaults 0."""
    limit = _clamp_int(
        request.args.get("limit"),
        K.PAGE_LIMIT_DEFAULT, K.PAGE_LIMIT_MIN, K.PAGE_LIMIT_MAX,
    )
    offset = _clamp_int(request.args.get("offset"), K.PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)


def filter_exact(rows, field, param=None):
    """Exact-match query filter, combined conjunctively."""
    value = request.args.get(param or field)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
