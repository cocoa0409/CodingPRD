"""Standard response envelope helpers — see PRD §2.2."""

from flask import jsonify, g

from utils import new_request_id
import db
from datetime import datetime, timezone


def _stamp_meta():
    return {
        "api_request_id": getattr(g, "req_id", new_request_id()),
        "api_request_timestamp": getattr(g, "req_timestamp", _now_iso()),
    }


def _now_iso():
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def success(data, status=200, is_array=False, pagination=None):
    meta = _stamp_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_array else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": _stamp_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def no_content():
    # 204 with empty body per PRD §4 for DELETE autopay-mandate.
    return "", 204
