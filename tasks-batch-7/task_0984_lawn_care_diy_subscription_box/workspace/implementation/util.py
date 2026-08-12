import re
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from errors import raise_err, ERR_INVALID_REQUEST

_MD_RE = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value, field):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an ISO-8601 datetime string" % field)
    t = value.strip()
    iso = t[:-1] + "+00:00" if t.endswith("Z") else t
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is not a valid ISO-8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt3(dt):
    """Format an aware datetime as ISO-8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_ymd(value, field):
    """Parse a YYYY-MM-DD date string into a datetime.date."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a YYYY-MM-DD date string" % field)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is not a valid calendar date" % field)


def check_md(value, field):
    """Validate an MM-DD month-day string."""
    if not isinstance(value, str) or not _MD_RE.match(value.strip()):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an MM-DD month-day string" % field)
    return value.strip()


def round_half_up_cents(value):
    """Round a Decimal-compatible value to integer cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    """Decimal from a JSON number without float artifacts."""
    return Decimal(str(value))


# ---- JSON type guards (bool is a subclass of int in Python; exclude it) ----

def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a non-empty string" % field)
    return v.strip() if field != "email" else v  # keep email verbatim for case-insensitive compare


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be an integer" % field)
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    return v


def req_num(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' is required and must be a number" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def opt_bool(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a boolean" % field)
    return v
