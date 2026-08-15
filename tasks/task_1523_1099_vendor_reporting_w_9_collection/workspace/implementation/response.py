import uuid
from datetime import datetime, timezone
from flask import jsonify


def _request_meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": "req_" + uuid.uuid4().hex, "api_request_timestamp": ts}


def success_envelope(data, status=200, response_type="object", pagination=None):
    meta = _request_meta()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def error_envelope(error_id, status, message):
    return jsonify({
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
