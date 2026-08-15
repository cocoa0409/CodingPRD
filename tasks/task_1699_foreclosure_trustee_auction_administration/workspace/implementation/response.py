"""Response envelope helpers.

Envelope shape read verbatim from SCAFFOLD.yaml §1.0 / PRD §2.2:
  success: { "meta": {api_request_id, api_request_timestamp},
             "response_type": "object"|"array", "data": ... }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id", "message" } }
List responses add limit/offset/total_count/has_more to meta
(pagination_fields from §1.0; defaults limit=10 min 1 max 100, offset=0).
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from db import _format_iso
from errors import ApiError

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta():
    # Request-receipt timestamp, three fractional digits, UTC (PRD §2.2).
    ts = _format_iso(datetime.now(timezone.utc))
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Read limit/offset query params with scaffold §1.0 defaults.

    limit: default 10, min 1, max 100. offset: default 0. Non-integer or
    out-of-range values fall back to the default / nearest bound.
    """
    def _int(value, default, lo, hi):
        try:
            v = int(value)
        except (TypeError, ValueError):
            return default
        if v < lo:
            return lo
        if v > hi:
            return hi
        return v

    limit = _int(args.get("limit"), 10, 1, 100)
    offset = _int(args.get("offset"), 0, 0, 1 << 62)
    return limit, offset
