"""Response envelope helpers — structure fixed verbatim by SCAFFOLD §1.0 / PRD §2.2."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.5)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _request_id():
    # api_request_id starts with req_ (PRD §2.2).
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    """response_type 'object' for a single resource (PRD §2.2)."""
    body = {"meta": _meta(pagination), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    """response_type 'array'; pagination bookkeeping in meta (PRD §2.2/§2.3)."""
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
