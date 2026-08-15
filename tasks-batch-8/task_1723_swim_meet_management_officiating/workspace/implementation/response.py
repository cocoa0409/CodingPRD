"""Standard response envelope helpers (PRD section 2.2)."""

import secrets

from flask import jsonify

from db import iso3, wall_now


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": iso3(wall_now()),
    }


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total_count, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), code


def err_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )
