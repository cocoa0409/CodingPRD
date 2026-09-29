"""Core primitives: errors, response envelope, decimal + datetime helpers."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, InvalidOperation

from flask import jsonify


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# --------------------------------------------------------------------------
# request metadata
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# --------------------------------------------------------------------------
# decimal helpers
# --------------------------------------------------------------------------
D0 = Decimal("0")
MONEY = Decimal("0.01")
QTY = Decimal("0.001")
PRICE = Decimal("0.0001")
RATE = Decimal("0.000001")


def dq(value, places=2):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def money(value):
    return dq(value, 2)


def dstr(value, places=2):
    return str(dq(value, places))


def to_dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise InvalidOperation()
    return Decimal(str(value))


def ceil_div(numerator, denominator):
    return int((Decimal(numerator) / Decimal(denominator)).to_integral_value(rounding=ROUND_CEILING))


def floor_days(delta_seconds):
    return int(Decimal(delta_seconds // 86400))


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------
def parse_dt(text):
    """Parse an ISO-8601 datetime or plain date; returns aware UTC datetime or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    s = raw
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_date_only(text):
    return isinstance(text, str) and len(text.strip()) == 10 and text.strip().count("-") == 2


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_instant(dt):
    """Domain instants echo the logical clock's own reading: no padded fraction."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_dt(dt)


def fmt_date(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def day_end(dt):
    """Inclusive end of the calendar day containing dt."""
    return dt.replace(hour=23, minute=59, second=59, microsecond=999000)


def day_start(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def new_id():
    return str(uuid.uuid4())
