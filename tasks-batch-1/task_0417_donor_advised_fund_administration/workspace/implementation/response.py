"""Standard response envelope helpers.

The envelope shape is fixed by PRD Section 2.2 / SCAFFOLD 1.0:

  success: { "meta": { "api_request_id", "api_request_timestamp", [pagination...] },
             "response_type": "object" | "array", "data": {} | [] }
  error:   { "meta": { "api_request_id", "api_request_timestamp" },
             "response_type": "error",
             "data": { "error_id", "message" } }
"""
import datetime
import secrets
import string

from flask import jsonify

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    # PRD 2.2: server-generated unique identifier starting with "req_".
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return "req_" + body


def _timestamp():
    # PRD 2.2 / 2.4: ISO 8601 UTC timestamp with three fractional digits.
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def object_response(data, status=200):
    return success(data, status=status, response_type="object")


def array_response(items, pagination):
    return success(items, status=200, response_type="array", pagination=pagination)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
