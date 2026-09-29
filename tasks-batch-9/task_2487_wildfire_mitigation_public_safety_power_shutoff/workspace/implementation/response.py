"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""

import json
import random
import string
from decimal import Decimal

from flask import Response

import clock

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


class _Encoder(json.JSONEncoder):
    def default(self, o):  # pragma: no cover - defensive
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _json(payload, status):
    body = json.dumps(payload, cls=_Encoder)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    return _json({"meta": _meta(), "response_type": "object", "data": data}, status)


def list_response(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    payload = {
        "meta": _meta(meta_extra),
        "response_type": "array",
        "data": items,
    }
    return _json(payload, 200)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _json(payload, status)
