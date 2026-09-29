"""Response envelope helpers (PRD 2.2).

Success:
  {"meta": {"api_request_id": "...", "api_request_timestamp": "..."},
   "response_type": "object" | "array",
   "data": {...} | [...]}

List responses additionally carry limit / offset / total_count / has_more
inside meta.  Errors use response_type "error" and a data object holding
error_id and message.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from timeutil import format_instant

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_instant(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def empty_response(status=200):
    return object_response({}, status)


def list_response(rows, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
