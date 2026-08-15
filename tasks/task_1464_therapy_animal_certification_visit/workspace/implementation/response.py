"""Standard response envelope helpers (PRD §2.2 / §2.3)."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _wall_timestamp():
    """Envelope timestamp: ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count, http_status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """limit defaults 10 (min 1, max 100); offset defaults 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, args):
    """Sort by (_seq, ) creation order ascending and paginate."""
    limit, offset = parse_pagination(args)
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
