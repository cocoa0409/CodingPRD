"""Response envelope helpers — matches PRD §2.2 exactly.

Success: { "meta": {api_request_id, api_request_timestamp[, limit, offset,
           total_count, has_more]}, "response_type": "object"|"array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {"error_id", "message"} }
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": "req_" + uuid.uuid4().hex[:20], "api_request_timestamp": ts}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total, limit, offset):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _ser_val(v):
    if isinstance(v, datetime):
        d = v.astimezone(timezone.utc)
        return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def serialize(rec):
    """Serialize a stored record; internal keys (leading _) are stripped."""
    return {k: _ser_val(v) for k, v in rec.items() if not k.startswith("_")}


def serialize_list(recs):
    return [serialize(r) for r in recs]


def sort_created(recs):
    """created_at ASC, deterministic tiebreak by insertion order (never id-keyed)."""
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
