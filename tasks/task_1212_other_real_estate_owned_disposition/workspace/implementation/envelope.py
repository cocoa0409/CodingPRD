from flask import jsonify

import db
from util import req_id, iso3


def meta():
    return {
        "api_request_id": req_id(),
        "api_request_timestamp": iso3(db.clock),
    }


def success(data, code=200, response_type="object", pagination=None):
    m = meta()
    if pagination:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), code


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
