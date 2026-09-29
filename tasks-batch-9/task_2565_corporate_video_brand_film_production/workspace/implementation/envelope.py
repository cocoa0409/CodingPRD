"""Standard response envelope (PRD 2.2 / scaffold response_envelope)."""

from flask import jsonify

from store import iso, real_now, request_id


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(real_now()),
    }


def respond_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def respond_created(data):
    return respond_object(data, 201)


def respond_list(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
