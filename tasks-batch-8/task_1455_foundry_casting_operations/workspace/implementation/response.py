"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import uuid
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from db import wall_now
from util import render_ts


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": render_ts(wall_now()),
    }


def serialize_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return render_ts(v)
    if isinstance(v, dict):
        return {k: serialize_value(x) for k, x in v.items()
                if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(v, (list, tuple)):
        return [serialize_value(x) for x in v]
    return v


def serialize(rec):
    return {k: serialize_value(v) for k, v in rec.items() if not k.startswith("_")}


def ok_object(rec, code=200):
    data = serialize(rec) if isinstance(rec, dict) and "_seq" in rec else serialize_value(rec)
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(recs, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(recs)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in recs],
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
