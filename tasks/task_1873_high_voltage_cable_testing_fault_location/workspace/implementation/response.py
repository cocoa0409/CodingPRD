"""Standard response envelope helpers (PRD section 2.2)."""
import random
import string

from flask import jsonify

import db
import util


def _meta_base():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": util.iso(db.now())}


def success(data, response_type="object", code=200, pagination=None):
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def error(err):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
