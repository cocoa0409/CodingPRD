"""Response envelope helpers (PRD 2.2 / 2.3)."""

import json
import random
import re
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response, request

from db import clock, commit
from errors import ApiError

# ---------------------------------------------------------------------------
# JSON encoding: Decimal values must keep their declared scale (54.00, not 54).
# ---------------------------------------------------------------------------

_MARK_OPEN = "\u0001DEC:"
_MARK_CLOSE = "\u0001"
_TOKEN_RE = re.compile(r'"\\u0001DEC:(-?\d+(?:\.\d+)?)\\u0001"')


def _prepare(value):
    if isinstance(value, Decimal):
        return _MARK_OPEN + format(value, "f") + _MARK_CLOSE
    if isinstance(value, dict):
        return {k: _prepare(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_prepare(v) for v in value]
    return value


def dumps(payload):
    return _TOKEN_RE.sub(r"\1", json.dumps(_prepare(payload)))


# ---------------------------------------------------------------------------
# Timestamp formatting
# ---------------------------------------------------------------------------

def iso(moment):
    if moment is None:
        return None
    if isinstance(moment, str):
        return moment
    aware = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    aware = aware.astimezone(timezone.utc)
    return "%s.%03dZ" % (aware.strftime("%Y-%m-%dT%H:%M:%S"), aware.microsecond // 1000)


def iso_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

_ID_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(clock.now),
    }
    if extra:
        meta.update(extra)
    return meta


def _emit(payload, status):
    return Response(dumps(payload), status=status, mimetype="application/json")


def obj(data, status=200):
    commit()
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return obj(data, 201)


def collection(items, page_meta):
    commit()
    return _emit({"meta": _meta(page_meta), "response_type": "array", "data": items}, 200)


def error_response(exc):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return _emit(payload, exc.http_status)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    return int(text)


def pagination():
    limit = _int_param("limit", LIMIT_DEFAULT)
    offset = _int_param("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError("ERR_VALIDATION", "Query parameter 'limit' must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX))
    if offset < OFFSET_MIN:
        raise ApiError("ERR_VALIDATION", "Query parameter 'offset' must be zero or greater.")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def listing(rows, serializer):
    page, meta = paginate(rows)
    return collection([serializer(r) for r in page], meta)
