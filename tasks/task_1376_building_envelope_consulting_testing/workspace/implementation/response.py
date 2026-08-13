"""Response envelope helpers (PRD section 2.2)."""
import json
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app


def _request_id():
    return "req_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(24)
    )


def _meta_timestamp():
    # Server-generated ISO 8601 UTC timestamp with three fractional digits.
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return fmt_dt(obj)
    raise TypeError(f"not serializable: {type(obj)!r}")


def _respond(payload, status):
    return current_app.response_class(
        json.dumps(payload, default=_json_default),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _meta_timestamp(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    payload = {
        "meta": meta,
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return _respond(payload, status)


def error(error_id, http_status, message):
    payload = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _meta_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(payload, http_status)
