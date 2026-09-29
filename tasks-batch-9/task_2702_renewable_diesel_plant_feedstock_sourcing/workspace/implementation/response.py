"""Response envelope and row serialization (PRD section 2.2)."""
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

import store

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": store.iso(store.now()),
    }


def _value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return store.iso(v)
    if isinstance(v, list):
        return [_value(x) for x in v]
    if isinstance(v, dict):
        return {k: _value(x) for k, x in v.items()}
    return v


def public(row):
    out = {}
    for key, val in row.items():
        if key.startswith("_") or key == "version":
            continue
        out[key] = _value(val)
    out["created_at"] = store.iso(row["_created"])
    if "_updated" in row:
        out["updated_at"] = store.iso(row["_updated"])
        out["version"] = row["version"]
    return out


def ok(row, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(row)}
    return jsonify(body), status


def raw(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": _value(data)}
    return jsonify(body), status


def page(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [public(r) for r in window],
    }
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
