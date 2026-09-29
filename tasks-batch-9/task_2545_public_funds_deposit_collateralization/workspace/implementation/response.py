"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string

from flask import jsonify

import db

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": db.now_text(),
    }


def serialize(record):
    """Render a stored record: drop internals, unwrap timestamps."""
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = _value(value)
    return out


def _value(value):
    if isinstance(value, db.Ts):
        return value.text
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _value(v) for k, v in value.items() if not k.startswith("_")}
    return value


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def record_response(record, status=200):
    return object_response(serialize(record), status)


def list_response(records, limit, offset, total_count, serialized=False):
    page = records if serialized else [serialize(r) for r in records]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(page)) < total_count
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
