"""Standard response envelope (PRD 2.2)."""
import random
import string

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": db.now_iso(),
    }


def public(row):
    """Strip internal bookkeeping keys."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(data) if isinstance(data, dict) else data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [public(r) for r in rows]}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
