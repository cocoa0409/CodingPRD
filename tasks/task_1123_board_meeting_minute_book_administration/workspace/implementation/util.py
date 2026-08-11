"""Time handling, parsing, and primitive validation helpers.

All timestamps are stored at second precision (PRD section 2.8: "All
timestamps are compared at second precision") and serialized as ISO 8601
UTC with three fractional digits (PRD section 2.5).
"""

from datetime import datetime, timedelta, timezone

from errors import ERR_VALIDATION, raise_err

SECONDS_PER_DAY = 86400


def truncate_second(dt):
    return dt.replace(microsecond=0)


def parse_datetime(value, field):
    """Parse an ISO 8601 timestamp into an aware UTC datetime at second
    precision. Any malformed value is a schema error."""
    if not isinstance(value, str) or not value.strip():
        raise_err(ERR_VALIDATION, "Field '%s' must be an ISO 8601 timestamp string" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_VALIDATION, "Field '%s' is not a well-formed ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return truncate_second(dt)


def iso_ms(dt):
    """Serialize an aware UTC datetime as ISO 8601 with three fractional
    digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def wall_now_iso_ms():
    """Wall-clock timestamp for the meta envelope (3 fractional digits)."""
    return iso_ms(datetime.now(timezone.utc))


def add_days(dt, days):
    return dt + timedelta(days=days)  # days counted as 86,400 seconds each


def add_years(dt, years):
    """Anniversary-based year addition; clamps Feb 29 to Feb 28."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years
        return dt.replace(year=dt.year + years, day=28)


# --- Primitive body validators ------------------------------------------------

def body_dict(body):
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def req_field(body, field):
    if field not in body or body[field] is None:
        raise_err(ERR_VALIDATION, "Missing required field: %s" % field)
    return body[field]


def req_string(body, field):
    value = req_field(body, field)
    if not isinstance(value, str) or isinstance(value, bool):
        raise_err(ERR_VALIDATION, "Field '%s' must be a string" % field)
    return value


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str) or isinstance(value, bool):
        raise_err(ERR_VALIDATION, "Field '%s' must be a string" % field)
    return value


def req_int(body, field):
    value = req_field(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_VALIDATION, "Field '%s' must be an integer" % field)
    return value


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field)


def req_bool(body, field):
    value = req_field(body, field)
    if not isinstance(value, bool):
        raise_err(ERR_VALIDATION, "Field '%s' must be a boolean" % field)
    return value


def req_enum(body, field, members):
    value = req_field(body, field)
    if not isinstance(value, str) or value not in members:
        raise_err(
            ERR_VALIDATION,
            "Field '%s' must be one of: %s" % (field, ", ".join(members)),
        )
    return value


def req_datetime(body, field):
    return parse_datetime(req_field(body, field), field)


def opt_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return parse_datetime(body[field], field)


def check_range_int(value, field, minimum=None, maximum=None):
    if minimum is not None and value < minimum:
        raise_err(ERR_VALIDATION, "Field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise_err(ERR_VALIDATION, "Field '%s' must be <= %s" % (field, maximum))
    return value
