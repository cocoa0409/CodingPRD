"""Response envelope helpers (PRD 2.2). Success:
{ "meta": {api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]},
  "response_type": "object" | "array", "data": ... }
Error:
{ "meta": {api_request_id, api_request_timestamp}, "response_type": "error",
  "data": {error_id, message} }
Timestamps are ISO 8601 UTC with three fractional digits."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits; None passes through."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
