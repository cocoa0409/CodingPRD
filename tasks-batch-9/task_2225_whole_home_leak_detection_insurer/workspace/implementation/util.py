"""Formatting, parsing, rounding and body-validation helpers."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from errors import ApiError, bad_request

D = Decimal

_E164 = re.compile(r"^\+[1-9]\d{1,14}$")
_ALNUM_UPPER = re.compile(r"^[A-Z0-9]+$")
STATE_CODE = re.compile(r"^[A-Z]{2}$")
POSTAL_CODE = re.compile(r"^\d{5}$")


# ---------------------------------------------------------------- ids / time
def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO-8601 UTC instant.  Returns an aware UTC datetime or raises
    ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a timestamp")
    text = value.strip()
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("unparseable timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_minutes(delta):
    return int(delta.total_seconds() // 60)


def minutes_between(later, earlier):
    return D(str((later - earlier).total_seconds())) / D("60")


# ---------------------------------------------------------------- rounding
def rhu(value, places):
    """Round half up at `places` decimals; returns Decimal."""
    if isinstance(value, Decimal):
        dec = value
    else:
        dec = D(str(value))
    exp = D(1).scaleb(-places)
    return dec.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def num(value, places=None):
    """Render a Decimal (or number) as a JSON-friendly float."""
    if value is None:
        return None
    if places is not None:
        value = rhu(value, places)
    if not isinstance(value, Decimal):
        value = D(str(value))
    return float(value)


def to_dec(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return D(str(value))


# ---------------------------------------------------------------- body helpers
def get_body(req):
    if not req.data:
        return {}
    try:
        body = req.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        raise bad_request("Request body is not valid JSON.")
    if body is None:
        raise bad_request("Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object.")
    return body


def _missing(body, field):
    return field not in body or body[field] is None


def req_string(body, field, min_len=1, max_len=None, pattern=None, lower=False):
    if _missing(body, field):
        raise bad_request("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % field)
    if len(value) < min_len or (max_len is not None and len(value) > max_len):
        raise bad_request("Field '%s' has an invalid length." % field)
    if lower and value != value.lower():
        raise bad_request("Field '%s' must be lowercase." % field)
    if pattern is not None and not pattern.match(value):
        raise bad_request("Field '%s' is malformed." % field)
    return value


def opt_string(body, field, min_len=1, max_len=None, default=None, pattern=None):
    if _missing(body, field):
        return default
    return req_string(body, field, min_len=min_len, max_len=max_len, pattern=pattern)


def req_enum(body, field, allowed):
    if _missing(body, field):
        raise bad_request("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if _missing(body, field):
        return default
    return req_enum(body, field, allowed)


def req_bool(body, field, default=None):
    if _missing(body, field):
        if default is None:
            raise bad_request("Field '%s' is required." % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return value


def opt_bool_default(body, field, default=False):
    if _missing(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return value


def req_int(body, field, minimum=None, maximum=None):
    if _missing(body, field):
        raise bad_request("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its minimum." % field)
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' is above its maximum." % field)
    return value


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if _missing(body, field):
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_number(body, field, minimum=None, maximum=None):
    """Numeric field; returns Decimal."""
    if _missing(body, field):
        raise bad_request("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '%s' must be a number." % field)
    try:
        dec = D(str(value))
    except InvalidOperation:
        raise bad_request("Field '%s' must be a number." % field)
    if minimum is not None and dec < minimum:
        raise bad_request("Field '%s' is below its minimum." % field)
    if maximum is not None and dec > maximum:
        raise bad_request("Field '%s' is above its maximum." % field)
    return dec


def opt_number(body, field, minimum=None, maximum=None, default=None):
    if _missing(body, field):
        return default
    return req_number(body, field, minimum=minimum, maximum=maximum)


def req_datetime(body, field):
    if _missing(body, field):
        raise bad_request("Field '%s' is required." % field)
    try:
        return parse_dt(body[field])
    except ValueError:
        raise bad_request("Field '%s' must be an ISO-8601 UTC timestamp." % field)


def opt_datetime(body, field, default=None):
    if _missing(body, field):
        return default
    return req_datetime(body, field)


def req_e164(body, field):
    return req_string(body, field, min_len=2, max_len=16, pattern=_E164)


def req_upper(body, field, min_len, max_len):
    value = req_string(body, field, min_len=min_len, max_len=max_len)
    if value != value.upper():
        raise bad_request("Field '%s' must be uppercase." % field)
    return value


E164 = _E164
