"""Standard response envelope helpers.

Success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
           "response_type": "object" | "array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""

import secrets
import string

from flask import jsonify

from util import wallclock_iso


_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(22))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": wallclock_iso(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
