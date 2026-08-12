"""Standard response envelope helpers (scaffold §1.0 / PRD §2.2)."""
from flask import jsonify

import db
from util import fmt_dt, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(db.now()),
    }


def success_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination, status=200):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
