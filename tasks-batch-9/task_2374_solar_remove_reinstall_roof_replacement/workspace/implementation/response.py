"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from db import db

_ALNUM = string.ascii_uppercase + string.digits


def iso(value):
    """Render an instant as ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def build_meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(db.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def serialize(row):
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = iso(value) if isinstance(value, datetime) else value
    return out


def ok(data, status=200):
    body = {
        "meta": build_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_row(row, status=200):
    return ok(serialize(row), status)


def ok_list(rows, limit, offset, total_count):
    body = {
        "meta": build_meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + len(rows)) < total_count,
            }
        ),
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return jsonify(error_body(error_id, message)), status
