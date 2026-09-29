"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string

from flask import jsonify

from store import iso, now

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso(now()),
    }


def object_response(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def array_response(items, limit, offset, total_count, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), code


def error_response(error_id, message, http_status):
    return (
        jsonify({
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        }),
        http_status,
    )


def paginate(rows, limit, offset):
    """Offset pagination applied after ordering/ranking (PRD 2.3)."""
    total = len(rows)
    return rows[offset:offset + limit], total
