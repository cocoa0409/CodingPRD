"""Response envelope helpers (PRD section 2.2)."""

from flask import jsonify

import store


def _base_meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.request_timestamp(),
    }


def ok(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(items, page_meta, status=200):
    meta = _base_meta()
    meta.update(page_meta)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
