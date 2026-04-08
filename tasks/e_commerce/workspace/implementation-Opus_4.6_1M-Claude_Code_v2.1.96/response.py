import uuid
from datetime import datetime, timezone
from flask import jsonify


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
           f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def make_request_id():
    return "mkt_" + uuid.uuid4().hex[:20]


def success_response(data, status_code=200, pagination=None):
    meta = {
        "api_request_id": make_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)

    response_type = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status_code


def error_response(error_id, message, status_code):
    meta = {
        "api_request_id": make_request_id(),
        "api_request_timestamp": now_iso(),
    }
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status_code
