"""Response envelope helpers (PRD 2.2, 2.3)."""

from datetime import datetime, timezone

from flask import jsonify

from store import ordered, serialize, serialize_all
from util import request_id


def _meta():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)
    return {"api_request_id": request_id(), "api_request_timestamp": stamp}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def resource_response(rec, status=200):
    return object_response(serialize(rec), status)


def collection_response(records, limit, offset):
    """List endpoints: created_at ascending, then offset pagination."""
    rows = ordered(list(records))
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response(serialize_all(page), limit, offset, total)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
