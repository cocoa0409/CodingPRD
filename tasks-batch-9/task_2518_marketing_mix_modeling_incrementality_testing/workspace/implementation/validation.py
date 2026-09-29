"""Request body / query validation helpers.

Every failure raised here is ERR_INVALID_REQUEST (PRD section 2.5) unless a caller
explicitly overrides the error id.
"""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

MISSING = object()


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def get_body(required=True):
    if not request.data:
        if required:
            return {}
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid("Request body must be a JSON object.")
    return body


# --------------------------------------------------------------- primitives

def _present(body, name, required, default):
    if name not in body or body[name] is None:
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    return body[name]


def field_string(body, name, required=True, default=None, pattern=None,
                 min_len=None, max_len=None):
    value = _present(body, name, required, default)
    if value is default and (name not in body or body.get(name) is None):
        return default
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
    if pattern is not None and re.match(pattern, value) is None:
        raise invalid("Field '%s' does not match the required format." % name)
    return value


def field_enum(body, name, choices, required=True, default=None):
    value = _present(body, name, required, default)
    if value is default and (name not in body or body.get(name) is None):
        return default
    if not isinstance(value, str) or value not in choices:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(sorted(choices))))
    return value


def field_bool(body, name, required=False, default=None):
    value = _present(body, name, required, default)
    if value is default and (name not in body or body.get(name) is None):
        return default
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def field_int(body, name, required=True, default=None, minimum=None, maximum=None):
    value = _present(body, name, required, default)
    if value is default and (name not in body or body.get(name) is None):
        return default
    if isinstance(value, bool):
        raise invalid("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if not float(value).is_integer():
            raise invalid("Field '%s' must be an integer." % name)
        result = int(value)
    else:
        raise invalid("Field '%s' must be an integer." % name)
    if minimum is not None and result < minimum:
        raise invalid("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and result > maximum:
        raise invalid("Field '%s' must be at most %s." % (name, maximum))
    return result


def field_decimal(body, name, required=True, default=None, minimum=None, maximum=None,
                  max_places=None, exclusive_minimum=None, exclusive_maximum=None):
    value = _present(body, name, required, default)
    if value is default and (name not in body or body.get(name) is None):
        return default
    if isinstance(value, bool):
        raise invalid("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, float)):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            raise invalid("Field '%s' must be a number." % name)
    else:
        raise invalid("Field '%s' must be a number." % name)
    if not result.is_finite():
        raise invalid("Field '%s' must be a finite number." % name)
    if max_places is not None:
        exponent = result.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > max_places:
            raise invalid("Field '%s' carries more than %d decimal places." % (name, max_places))
    if minimum is not None and result < Decimal(str(minimum)):
        raise invalid("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and result > Decimal(str(maximum)):
        raise invalid("Field '%s' must be at most %s." % (name, maximum))
    if exclusive_minimum is not None and result <= Decimal(str(exclusive_minimum)):
        raise invalid("Field '%s' must be greater than %s." % (name, exclusive_minimum))
    if exclusive_maximum is not None and result >= Decimal(str(exclusive_maximum)):
        raise invalid("Field '%s' must be less than %s." % (name, exclusive_maximum))
    return result


def field_array(body, name, required=True, default=None, min_items=None, max_items=None):
    value = _present(body, name, required, default)
    if value is default and (name not in body or body.get(name) is None):
        return default
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % name)
    if min_items is not None and len(value) < min_items:
        raise invalid("Field '%s' must carry at least %d items." % (name, min_items))
    if max_items is not None and len(value) > max_items:
        raise invalid("Field '%s' must carry at most %d items." % (name, max_items))
    return value


def field_id_array(body, name, required=True, default=None, min_items=None, max_items=None,
                   distinct=False):
    values = field_array(body, name, required, default, min_items, max_items)
    if values is None:
        return None
    for item in values:
        if not isinstance(item, str) or item.strip() == "":
            raise invalid("Field '%s' must be an array of identifier strings." % name)
    if distinct and len(set(values)) != len(values):
        raise invalid("Field '%s' must not repeat an identifier." % name)
    return values


# ------------------------------------------------------------------- dates

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(text, name):
    """Parse an ISO 8601 instant. Returns a timezone-aware UTC datetime."""
    if not isinstance(text, str) or text.strip() == "":
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    raw = text.strip()
    if _DATE_ONLY.match(raw):
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise invalid("Field '%s' is not a valid date." % name)
        return parsed.replace(tzinfo=timezone.utc)
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        if parsed.utcoffset() != timedelta(0):
            raise invalid("Field '%s' must be expressed in UTC." % name)
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def field_instant(body, name, required=True, default=None):
    """Returns (raw_string, datetime) or (None, None)."""
    value = _present(body, name, required, default)
    if name not in body or body.get(name) is None:
        return None, None
    return value if isinstance(value, str) else str(value), parse_instant(value, name)


def field_date(body, name, required=True, default=None):
    """A UTC-midnight ISO 8601 date. Returns (raw_string, date) or (None, None)."""
    value = _present(body, name, required, default)
    if name not in body or body.get(name) is None:
        return None, None
    moment = parse_instant(value, name)
    if (moment.hour, moment.minute, moment.second, moment.microsecond) != (0, 0, 0, 0):
        raise invalid("Field '%s' must be a UTC-midnight instant." % name)
    return value.strip(), moment.date()


def date_style(raw):
    """Remember the wire shape a client used so computed dates echo the same shape."""
    if not isinstance(raw, str):
        return "date"
    if "T" not in raw:
        return "date"
    if "." in raw:
        return "millis"
    return "seconds"


def format_date(value, style):
    if style == "millis":
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    if style == "seconds":
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return value.isoformat()


def query_bool(args, name, default=False):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise invalid("Query parameter '%s' must be a boolean." % name)
