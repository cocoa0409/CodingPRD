"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string

from flask import jsonify

from timeutil import fmt_iso, wall_now

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_iso(wall_now()),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count, has_more, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def paged(rows):
    """Apply §2.3 ordering + pagination and answer with the list envelope."""
    from store import public, sort_created_asc
    from validators import pagination

    limit, offset = pagination()
    ordered = sort_created_asc(rows)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    has_more = (offset + len(window)) < total
    return ok_list([public(r) for r in window], limit, offset, total, has_more)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
