"""Response envelope helpers (PRD section 2.2) and JSON serialization.

Decimal values are emitted as raw JSON numbers (never as strings and never
through float) so that a stored 80.00 leaves the server as 80.00.
"""

import json
import random
import re
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from flask import Response

_TOKEN = uuid.uuid4().hex
_DEC_MARK = "@@%s:" % _TOKEN
_DEC_RE = re.compile(r'"@@' + _TOKEN + r':([^"]*)@@"')

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def public(value):
    """Recursively convert a stored row into its JSON-ready shape.

    Keys beginning with '_' are internal bookkeeping and never serialized.
    """
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [public(v) for v in value]
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return _DEC_MARK + str(value) + "@@"
    return value


def _dumps(payload):
    text = json.dumps(payload, ensure_ascii=False)
    return _DEC_RE.sub(lambda m: m.group(1), text)


def _meta(pagination=None):
    from db import db

    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(db.now),
    }
    if pagination:
        meta.update(pagination)
    return meta


def _envelope(response_type, data, status, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return Response(_dumps(body), status=status, mimetype="application/json")


def ok(data):
    return _envelope("object", public(data), 200)


def created(data):
    return _envelope("object", public(data), 201)


def listing(rows, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    }
    return _envelope("array", [public(r) for r in rows], 200, pagination)


def error(error_id, message, status):
    return _envelope("error", {"error_id": error_id, "message": message}, status)
