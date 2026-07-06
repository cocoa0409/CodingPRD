"""Response envelope helpers. Envelope fields match SCAFFOLD.yaml/PRD §2.2."""
from flask import jsonify
from util import gen_request_id, iso_now
import db


def _base_meta():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": iso_now(db.now()),
    }


def ok(data, status=200):
    """2xx single-resource response."""
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_ok(items, limit, offset, total_count):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err(error_id, message, http_status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
