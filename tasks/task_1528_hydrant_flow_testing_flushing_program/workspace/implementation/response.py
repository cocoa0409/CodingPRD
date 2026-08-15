"""Response envelope helpers. Success and error envelopes follow PRD section 2.2
exactly: meta {api_request_id, api_request_timestamp}, response_type, data.
List responses add limit/offset/total_count/has_more into meta."""
import uuid

from flask import jsonify

import db
from timeutil import fmt


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt(db.now()),
    }


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, pagination, code=200):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
