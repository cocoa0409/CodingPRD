"""Response-envelope helpers and the ApiError exception type."""

import random
import string
from datetime import datetime

from flask import jsonify

from store import db, fmt_ts


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(db.now()),
    }


def success(data, response_type="object", http_status=200, pagination=None):
    meta = _base_meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), http_status


def error(error_id, http_status, message=""):
    meta = _base_meta()
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), http_status
