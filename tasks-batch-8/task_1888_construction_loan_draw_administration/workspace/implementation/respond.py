"""Response envelope helpers per PRD §2.2 / SCAFFOLD response_envelope."""

import secrets
import string

from flask import jsonify

from db import now_iso

_ALNUM = string.ascii_letters + string.digits


def _meta():
    rid = "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))
    return {"api_request_id": rid, "api_request_timestamp": now_iso()}


def success(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def success_list(page, total, limit, offset):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": m, "response_type": "array", "data": page}), 200


def error_response(error_id, status, message):
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
