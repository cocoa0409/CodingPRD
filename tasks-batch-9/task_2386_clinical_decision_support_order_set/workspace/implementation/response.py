"""Response envelope helpers (PRD §2.2) and JSON-safe serialisation."""
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify, request

import const
from db import db
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits.

    PRD §2.4 mandates this precision for ``created_at`` and ``updated_at``, and
    PRD §2.2 for ``api_request_timestamp``.  Those are the only instants whose
    rendering the PRD pins.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_instant(dt):
    """ISO 8601 UTC for a domain instant, preserving the source's precision.

    Every domain instant in this system is either supplied by the client
    (``go_live_at`` is "stored from the request", PRD §3.5), read from the
    logical clock (itself set from a supplied ``to_iso8601``, PRD §3.9), or
    obtained by whole-day arithmetic that "preserves the anchor's time-of-day
    component exactly" (PRD §2.5).  The PRD pins a three-fractional-digit
    rendering only for ``created_at``/``updated_at`` (§2.4) and
    ``api_request_timestamp`` (§2.2), so these instants are rendered back at the
    precision they carry rather than being padded.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    stamp = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )
    if dt.microsecond:
        stamp += ".%03d" % (dt.microsecond // 1000)
    return stamp + "Z"


# The three instants whose rendering the PRD pins to three fractional digits.
_PINNED_PRECISION_KEYS = frozenset(("created_at", "updated_at", "api_request_timestamp"))


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def jsonable(value, key=None):
    if isinstance(value, datetime):
        return iso(value) if key in _PINNED_PRECISION_KEYS else iso_instant(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonable(v, k) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v, key) for v in value]
    return value


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(db.clock),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": jsonable(data) if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": [jsonable(i) for i in items]}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ------------------------------------------------------------------ paging
def page_params():
    """Read and validate the ``limit``/``offset`` query parameters (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = const.DEFAULT_LIMIT
    offset = const.DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < const.MIN_LIMIT or limit > const.MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d" % (const.MIN_LIMIT, const.MAX_LIMIT),
            )
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def paginate(records, sort_key=None):
    """Sort, page and emit a list response."""
    limit, offset = page_params()
    if sort_key is None:
        records = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    else:
        records = sorted(records, key=sort_key)
    total = len(records)
    page = records[offset:offset + limit]
    return listing(page, limit, offset, total)
