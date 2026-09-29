"""Response envelope helpers (PRD 2.2 / SCAFFOLD response_envelope)."""

import random
import string

from flask import jsonify

import db

_ALPHANUM = string.ascii_uppercase + string.digits

# pagination_fields / pagination_defaults from SCAFFOLD response_envelope
PAGE_LIMIT_FIELD = "limit"
PAGE_OFFSET_FIELD = "offset"
PAGE_TOTAL_FIELD = "total_count"
PAGE_MORE_FIELD = "has_more"
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso_ts(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta[PAGE_LIMIT_FIELD] = limit
    meta[PAGE_OFFSET_FIELD] = offset
    meta[PAGE_TOTAL_FIELD] = total_count
    meta[PAGE_MORE_FIELD] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
