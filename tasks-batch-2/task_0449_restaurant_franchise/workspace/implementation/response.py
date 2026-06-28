"""Standard response envelope helpers.

Envelope structure read verbatim from SCAFFOLD §1.0 response_envelope and
PRD §2.2:
  success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
             "response_type": "object"|"array", "data": {} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": "ERR_XXX", "message": "..." } }

api_request_id starts with "req_"; api_request_timestamp is ISO 8601 UTC with
three fractional digits (PRD §2.2).
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.2 / §2.4)."""
    dt = datetime.now(timezone.utc)
    # millisecond precision, trailing 'Z'
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
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


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
