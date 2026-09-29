"""The standard response envelope (PRD 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from util import iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def serialize(row):
    """Public representation of a stored row: private keys dropped, datetimes formatted."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso(value)
        elif isinstance(value, list):
            out[key] = [
                iso(item) if isinstance(item, datetime) else item for item in value
            ]
        else:
            out[key] = value
    return out


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data) if isinstance(data, dict) else data}
    return jsonify(body), status


def ok_raw(data, status=200):
    """2xx response whose data is a plain dict already in wire form."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [serialize(r) for r in rows]}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
