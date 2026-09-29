"""Response envelope of PRD section 2.2."""

import random
import string

from flask import jsonify

from store import iso_now

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_now(),
    }


def ok(data, status=200):
    return (
        jsonify({"meta": base_meta(), "response_type": "object", "data": data}),
        status,
    )


def ok_array(items, limit=10, offset=0, total=None, status=200):
    if total is None:
        total = len(items)
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return (
        jsonify({"meta": meta, "response_type": "array", "data": items}),
        status,
    )


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(rows, limit, offset):
    """Apply the window and return (page, total_count)."""
    total = len(rows)
    return rows[offset:offset + limit], total
