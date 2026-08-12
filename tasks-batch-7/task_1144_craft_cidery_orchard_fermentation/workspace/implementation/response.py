"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string
from datetime import timezone

from flask import jsonify, request

import db


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(value):
    """Parse an ISO 8601 timestamp to an aware UTC datetime."""
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        from datetime import datetime

        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError(f"not an ISO8601 timestamp: {value!r}")


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": ts(db.now()),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(records, serializer):
    """records: pre-filtered list of stored dicts. Sorts by created_at ASC
    (insertion sequence as stable tie-break) and applies limit/offset."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)

    def _int(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _int("limit", 10)
    limit = max(1, min(100, limit))
    offset = _int("offset", 0)
    offset = max(0, offset)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)
