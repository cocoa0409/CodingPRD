"""Response envelope, timestamp formatting and money helpers."""

import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits


# --------------------------------------------------------------------------- #
# timestamps
# --------------------------------------------------------------------------- #

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.6)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def trunc_ms(dt):
    """Instants are compared to the millisecond (PRD §2.12)."""
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def parse_dt(value):
    """Parse an ISO 8601 UTC instant. Returns None when malformed."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return trunc_ms(dt.astimezone(timezone.utc))


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


# --------------------------------------------------------------------------- #
# money
# --------------------------------------------------------------------------- #

def rhu(value):
    """Round half up to a whole cent (PRD §2.8)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------- #
# envelope (PRD §2.2)
# --------------------------------------------------------------------------- #

def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt(db.now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
