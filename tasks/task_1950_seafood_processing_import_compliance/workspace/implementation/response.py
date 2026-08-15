"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from utils import iso_z3


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": iso_z3(datetime.now(timezone.utc)),
    }


def success(data, response_type="object", status=200, page_meta=None):
    meta = _meta()
    if page_meta:
        meta.update(page_meta)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
