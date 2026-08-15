"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2)."""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from util import fmt_ms


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": fmt_ms(datetime.now(timezone.utc)),
    }


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
