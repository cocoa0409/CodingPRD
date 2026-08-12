"""Standard response envelope helpers per PRD §2.2 / §2.3.

Success:  { "meta": {api_request_id, api_request_timestamp[, limit, offset,
            total_count, has_more]}, "response_type": "object"|"array",
            "data": ... }
Error:    { "meta": {api_request_id, api_request_timestamp},
            "response_type": "error",
            "data": {"error_id": ..., "message": ...} }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _request_timestamp():
    # Envelope timestamps are wall-clock request metadata (PRD §2.2 example);
    # three fractional digits, UTC.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def success_object(data, http_status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), http_status


def success_list(items, pagination, http_status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
