"""Time, decimal, and request-payload validation helpers."""

import math
import re
import uuid
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import ApiError, bad_request

UTC = timezone.utc

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def now_request_ts():
    """Wall-clock timestamp for the meta envelope (3 fractional digits)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def fmt_ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits (created_at/updated_at)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def fmt_dt(dt):
    """Logical-clock timestamps: seconds precision when whole, else 3 fractional digits."""
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_datetime_value(value, field):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date_value(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise bad_request("Field '%s' must be a YYYY-MM-DD date string" % field)
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise bad_request("Field '%s' is not a valid calendar date" % field)


def dec(value):
    """Convert an int/float/str JSON number to Decimal."""
    return Decimal(str(value))


def round_half_up_cents(x):
    """Round a Decimal to integer cents, half up."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num_out(d):
    """Serialize a Decimal as an int when integral, else float."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        return d
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Request body validation helpers
# ---------------------------------------------------------------------------

def json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_field(body, name):
    if not _present(body, name):
        raise bad_request("Missing required field: %s" % name)
    return body[name]


def opt_field(body, name, default=None):
    if not _present(body, name):
        return default
    return body[name]


def as_str(value, name):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean" % name)
    return value


def as_number(value, name):
    """JSON number -> Decimal. Booleans and non-finite values rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number" % name)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise bad_request("Field '%s' must be a finite number" % name)
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise bad_request("Field '%s' must be a number" % name)


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise bad_request(
            "Field '%s' must be one of: %s" % (name, ", ".join(allowed)))
    return value


def as_str_list(value, name):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise bad_request("Field '%s' must be an array of strings" % name)
    return value
