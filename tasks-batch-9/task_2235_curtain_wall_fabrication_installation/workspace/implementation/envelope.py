"""Uniform response envelope (PRD §2.2)."""

from flask import jsonify

from store import now_iso, request_id


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(rows, pagination=None, status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), status


def fail(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
