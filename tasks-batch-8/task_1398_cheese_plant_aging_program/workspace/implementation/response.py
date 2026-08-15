"""Standard response envelope helpers (PRD section 2.2)."""

import secrets
from datetime import datetime

from flask import jsonify

from db import now


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": fmt_ts(now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def success(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def serialize(rec):
    """Strip internal keys and format datetime values."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            v = fmt_ts(v)
        out[k] = v
    return out
