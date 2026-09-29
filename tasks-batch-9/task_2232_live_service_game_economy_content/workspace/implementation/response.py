"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""
import random
import string

from flask import jsonify, g

import db
from util import iso, utcnow

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(utcnow()),
    }


def touch(record):
    """Bump updated_at / version once per request for every mutated record."""
    if record is None:
        return record
    if "version" not in record:
        return record
    touched = getattr(g, "touched_ids", None)
    if touched is None:
        touched = set()
        g.touched_ids = touched
    key = id(record)
    if key in touched:
        return record
    touched.add(key)
    record["version"] = record["version"] + 1
    record["updated_at"] = iso(db.now())
    return record


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(records, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(records)) < total_count
    body = {"meta": meta, "response_type": "array", "data": records}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
