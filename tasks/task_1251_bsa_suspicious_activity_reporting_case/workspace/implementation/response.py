"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
from flask import jsonify

from util import iso_z, new_request_id, wall_now


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_z(wall_now()),
    }


def success(data, status=200, response_type="object"):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    return jsonify(body), status


def paginated(all_items, limit, offset):
    total = len(all_items)
    page = all_items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
