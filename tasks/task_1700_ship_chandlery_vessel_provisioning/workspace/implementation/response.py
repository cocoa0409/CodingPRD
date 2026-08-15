"""Response envelope helpers.

Envelope shape read verbatim from SCAFFOLD.yaml §1.0 / PRD §2.2:
  success: { "meta": {api_request_id, api_request_timestamp},
             "response_type": "object"|"array", "data": ... }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id", "message" } }
List responses add limit/offset/total_count/has_more to meta.
The api_request_timestamp is an ISO8601 UTC timestamp with three
fractional digits; it is a *response* timestamp (request receipt), not an
entity field, so it uses wall-clock receipt time per PRD §2.2 example.
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta():
    # Request-receipt timestamp (wall clock), three fractional digits, UTC —
    # the PRD §2.2 envelope example form ("2025-05-24T10:30:00.123Z").
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(now.microsecond // 1000)
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
    """Read limit/offset query params with scaffold defaults (§1.0).

    Defaults: limit=10 (min 1, max 100), offset=0. Non-integer or
    out-of-range values are clamped to the nearest admissible value; a
    non-parseable value falls back to the default (spec floor/ceiling).
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
