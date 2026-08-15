"""Standard response envelope helpers.

Success: { "meta": {api_request_id, api_request_timestamp[, limit, offset,
           total_count, has_more]}, "response_type": "object"|"array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""

import secrets
import string

from flask import jsonify

from db import fmt_common, now

_ALPHANUM = string.ascii_letters + string.digits


def new_request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_common(now()),
    }


def success(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"]["limit"] = pagination["limit"]
        body["meta"]["offset"] = pagination["offset"]
        body["meta"]["total_count"] = pagination["total_count"]
        body["meta"]["has_more"] = pagination["has_more"]
    return jsonify(body), status


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
