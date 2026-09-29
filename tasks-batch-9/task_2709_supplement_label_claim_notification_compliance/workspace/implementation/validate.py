"""Body-shape screening (PRD section 2.7 rank 4 -> ERR_VALIDATION)."""

from datetime import datetime

from flask import request

import errors
from errors import fail

MISSING = object()


def body():
    """The JSON request body as a dict.  A missing body is an empty object."""
    try:
        raw = request.get_json(silent=True, force=True)
    except Exception:  # pragma: no cover - defensive
        raw = None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail(errors.ERR_VALIDATION, "The request body must be a JSON object.")
    return raw


def _present(b, name):
    return name in b


def _missing(name):
    fail(errors.ERR_VALIDATION, "Field '%s' is required." % name)


def _bad(name, why):
    fail(errors.ERR_VALIDATION, "Field '%s' %s." % (name, why))


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


# --- required ---------------------------------------------------------------

def req_str(b, name):
    if not _present(b, name):
        _missing(name)
    value = b[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    return value


def req_enum(b, name, allowed):
    value = req_str(b, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def req_bool(b, name):
    if not _present(b, name):
        _missing(name)
    value = b[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_number(b, name, gt=None, ge=None, le=None):
    if not _present(b, name):
        _missing(name)
    value = b[name]
    if not is_number(value):
        _bad(name, "must be a number")
    _range(name, value, gt, ge, le)
    return value


def req_int(b, name, gt=None, ge=None, le=None):
    if not _present(b, name):
        _missing(name)
    value = b[name]
    if not is_integer(value):
        _bad(name, "must be an integer")
    _range(name, value, gt, ge, le)
    return value


def req_date(b, name):
    value = req_str(b, name)
    return parse_date(name, value)


def req_str_array(b, name):
    if not _present(b, name):
        _missing(name)
    value = b[name]
    if not isinstance(value, list):
        _bad(name, "must be an array of strings")
    for item in value:
        if not isinstance(item, str):
            _bad(name, "must be an array of strings")
    return list(value)


# --- optional ---------------------------------------------------------------

def opt_str(b, name, default=None, allow_null=True):
    if not _present(b, name):
        return default
    value = b[name]
    if value is None:
        if allow_null:
            return None
        _bad(name, "must be a string")
    if not isinstance(value, str):
        _bad(name, "must be a string")
    return value


def opt_enum(b, name, allowed, default=None, allow_null=True):
    if not _present(b, name):
        return default
    value = b[name]
    if value is None:
        if allow_null:
            return None
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_bool(b, name, default=None, allow_null=True):
    if not _present(b, name):
        return default
    value = b[name]
    if value is None and allow_null:
        return None
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_number(b, name, default=None, gt=None, ge=None, le=None, allow_null=True):
    if not _present(b, name):
        return default
    value = b[name]
    if value is None:
        if allow_null:
            return None
        _bad(name, "must be a number")
    if not is_number(value):
        _bad(name, "must be a number")
    _range(name, value, gt, ge, le)
    return value


def opt_int(b, name, default=None, gt=None, ge=None, le=None, allow_null=True):
    if not _present(b, name):
        return default
    value = b[name]
    if value is None:
        if allow_null:
            return None
        _bad(name, "must be an integer")
    if not is_integer(value):
        _bad(name, "must be an integer")
    _range(name, value, gt, ge, le)
    return value


def opt_date(b, name, default=None, allow_null=True):
    if not _present(b, name):
        return default
    value = b[name]
    if value is None:
        if allow_null:
            return None
        _bad(name, "must be a YYYY-MM-DD date string")
    if not isinstance(value, str):
        _bad(name, "must be a YYYY-MM-DD date string")
    return parse_date(name, value)


def opt_str_array(b, name, default=None):
    if not _present(b, name):
        return default
    return req_str_array(b, name)


# --- shared -----------------------------------------------------------------

def _range(name, value, gt, ge, le):
    if gt is not None and not value > gt:
        _bad(name, "must be greater than %s" % gt)
    if ge is not None and not value >= ge:
        _bad(name, "must be greater than or equal to %s" % ge)
    if le is not None and not value <= le:
        _bad(name, "must be less than or equal to %s" % le)


def parse_date(name, value):
    if not isinstance(value, str) or len(value) != 10:
        _bad(name, "must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        _bad(name, "must be a YYYY-MM-DD date string")


def parse_instant(name, value):
    """Parse an ISO 8601 UTC instant (the clock endpoint's `current_utc`)."""
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 UTC timestamp string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad(name, "must be an ISO 8601 UTC timestamp string")
    if parsed.tzinfo is None:
        from datetime import timezone

        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        from datetime import timezone

        parsed = parsed.astimezone(timezone.utc)
    return parsed
