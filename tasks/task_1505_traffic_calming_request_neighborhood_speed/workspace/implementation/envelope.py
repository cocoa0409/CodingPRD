"""Response envelope helpers (PRD §2.2, §2.3) and timestamp formatting."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import jsonify

from store import store


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.2)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(store.now),
    }


def dump(entity):
    """Serialize an entity dict: drop internal `_` fields, format datetimes,
    convert Decimals to floats. Dict insertion order defines field order."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def object_response(entity, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": dump(entity)}
    return jsonify(body), status


def raw_object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    body = {"meta": m, "response_type": "array", "data": [dump(e) for e in page]}
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


def sort_by_created(items):
    """PRD §2.3: list endpoints sort by creation timestamp ascending, oldest
    first; insertion sequence breaks ties (identical logical timestamps)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
