"""Standard response envelope helpers (PRD sections 2.2 / 2.3)."""
import secrets

from flask import jsonify

import db


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": db.now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if pagination is not None else "object"
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def list_of(items):
    """items: pre-filtered record dicts; paginates and serializes via `ser`."""
    from helpers import paginate
    page, meta = paginate(items)
    return page, meta


def error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
