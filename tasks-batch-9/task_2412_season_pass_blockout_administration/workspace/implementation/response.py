"""Response envelope helpers (PRD 2.2 / SCAFFOLD response_envelope)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import fmt_instant

ALPHANUM = string.ascii_uppercase + string.digits

# response_envelope.pagination_defaults
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_instant(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created_response(data):
    return object_response(data, 201)


def list_response(items, limit, offset):
    total = len(items)
    page = items[offset: offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
