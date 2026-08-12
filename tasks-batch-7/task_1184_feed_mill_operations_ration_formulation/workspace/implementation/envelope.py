"""Response envelope helpers (PRD section 2.2) and Decimal-aware JSON encoding."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify
from flask.json.provider import DefaultJSONProvider


class JSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            if obj == obj.to_integral_value():
                return int(obj)
            return float(obj)
        return DefaultJSONProvider.default(obj)


def _meta():
    request_id = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": request_id, "api_request_timestamp": timestamp}


def success(data, status=200, pagination=None):
    meta = _meta()
    response_type = "object"
    if pagination is not None:
        meta.update(pagination)
        response_type = "array"
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
