"""Response envelope helpers (PRD 2.2 / 2.3, SCAFFOLD response_envelope)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import public
from util import iso_instant

ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_instant(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def entity_response(record, status=200):
    return object_response(public(record), status)


def array_response(records, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(records)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) if isinstance(r, dict) else r for r in records],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
