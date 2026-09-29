"""Response envelope helpers.

Envelope shape is taken verbatim from PRD.md section 2.2 / SCAFFOLD.yaml
`response_envelope`:

    success: { "meta": {api_request_id, api_request_timestamp, [limit, offset,
               total_count, has_more]}, "response_type": "object"|"array",
               "data": {} }
    error:   { "meta": {...}, "response_type": "error",
               "data": {"error_id": ..., "message": ...} }
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def request_timestamp():
    # Wall-clock instant of the response, ISO 8601 UTC with three fractional
    # digits (PRD section 2.2).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    """Single-object success response."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(rows, pagination, status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), status


def fail(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
