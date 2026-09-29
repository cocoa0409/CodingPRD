"""Response envelope helpers (PRD 2.2) and row serialisation."""

from datetime import datetime, date
from decimal import Decimal

from flask import jsonify

import db
from util import UTC, fmt_dt, fmt_dt_sec, fmt_date, num

# The only datetime field the PRD pins to whole-second precision.
SECOND_PRECISION_FIELDS = frozenset(["response_deadline_at"])
VERBATIM_FIELDS = frozenset(["current_utc"])


def _meta():
    return {
        "api_request_id": db.db.next_request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(UTC)),
    }


def _convert(key, value):
    if isinstance(value, Decimal):
        return num(value)
    if isinstance(value, datetime):
        if key in SECOND_PRECISION_FIELDS:
            return fmt_dt_sec(value)
        return fmt_dt(value)
    if isinstance(value, date):
        return fmt_date(value)
    if isinstance(value, list):
        return [_convert(key, item) for item in value]
    if isinstance(value, dict):
        return dict((k, _convert(k, v)) for k, v in value.items())
    return value


def serialize(row):
    """Render a stored row, dropping internal (underscore-prefixed) keys."""
    db.commit()
    if row is None:
        return None
    out = {"id": row["id"]}
    for key, value in row.items():
        if key.startswith("_") or key == "id":
            continue
        out[key] = _convert(key, value)
    return out


def payload(data):
    """Convert an ad-hoc dict (report bodies) for JSON output."""
    db.commit()
    return dict((k, _convert(k, v)) for k, v in data.items())


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if isinstance(data, dict) else data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
