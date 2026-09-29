"""Request-shape validation (PRD 2.9 step 8) and pagination (PRD 2.3)."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def _missing(body, name, required, default):
    if required:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return default


def f_raw(body, name, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    return body[name]


def f_str(body, name, required=True, default=None, allow_empty=False):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    return value


def f_bool(body, name, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def f_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def f_num(body, name, required=True, default=None, minimum=None, maximum=None,
          exclusive_min=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (name, exclusive_min))
    return dec


def f_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def f_date(body, name, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str) or not DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a valid calendar date." % name)
    return value


def f_time(body, name, required=True, default=None):
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str) or not TIME_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an HH:MM 24-hour time." % name)
    return value


def f_datetime(body, name, required=True, default=None):
    """ISO 8601 UTC instant. The supplied representation is preserved verbatim."""
    if not _present(body, name):
        return _missing(body, name, required, default)
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    parse_iso_dt(value, name)
    return value


def parse_iso_dt(value, name="timestamp"):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % name)
    if parsed.tzinfo is None:
        from datetime import timezone
        parsed = parsed.replace(tzinfo=timezone.utc)
    from datetime import timezone as _tz
    return parsed.astimezone(_tz.utc)


def iso_date_part(value):
    """Date portion of an ISO 8601 instant, as YYYY-MM-DD."""
    return parse_iso_dt(value).date().isoformat()


# --------------------------------------------------------------------------
# query-string helpers
# --------------------------------------------------------------------------

def _q_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (min 0)."""
    limit = _q_int("limit", 10, 1, 100)
    offset = _q_int("offset", 0, 0, None)
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_date(name, required=False):
    value = request.args.get(name)
    if value is None or value == "":
        if required:
            fail("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
        return None
    if not DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be a YYYY-MM-DD date." % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be a valid calendar date." % name)
    return value


def paginate(items, limit, offset):
    return items[offset:offset + limit], len(items)
