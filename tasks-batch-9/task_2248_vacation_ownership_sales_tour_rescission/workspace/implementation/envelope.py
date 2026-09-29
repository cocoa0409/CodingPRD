"""Response envelope helpers (PRD 2.2) and per-request mutation bookkeeping."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import g, jsonify

from store import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def jsonable(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict(
            (k, jsonable(v)) for k, v in value.items() if not str(k).startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Mutation bookkeeping.  PRD 2.4/2.10: every record mutated by a request --
# directly or through a cascade -- has updated_at refreshed and version
# incremented exactly once for that request.
# --------------------------------------------------------------------------
def mark(entity):
    if entity is None:
        return
    dirty = getattr(g, "_dirty", None)
    if dirty is None:
        dirty = g._dirty = []
    for existing in dirty:
        if existing is entity:
            return
    dirty.append(entity)


def commit_dirty():
    dirty = getattr(g, "_dirty", None)
    if not dirty:
        return
    now = db.now()
    for entity in dirty:
        if "version" in entity:
            entity["updated_at"] = now
            entity["version"] = entity["version"] + 1
    g._dirty = []


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }
    if pagination:
        meta.update(pagination)
    return meta


def respond(data, status=200, response_type="object", pagination=None):
    commit_dirty()
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def ok(data):
    return respond(data, 200, "object")


def created(data):
    return respond(data, 201, "object")


def listing(rows, limit, offset):
    total = len(rows)
    page = rows[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return respond(page, 200, "array", pagination)


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
