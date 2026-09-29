"""Response envelope helpers (PRD 2.2)."""
import random
import string

from flask import jsonify

from db import now_iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": now_iso()}


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, limit, offset, status=200):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
