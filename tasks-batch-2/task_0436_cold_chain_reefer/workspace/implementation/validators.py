"""Body-field validation helpers — all raise ERR_INVALID_REQUEST (400) on failure.

Used by route handlers to enforce required presence, type, enum domain and
numeric range (PRD §2.6 well-formedness / validation priority 18).
"""

import datetime

from errors import err


def get_body(req):
    """Return the JSON body as a dict; reject non-object/invalid JSON."""
    raw = req.data or b""
    if (req.content_length in (None, 0)) and not raw.strip():
        return {}
    try:
        data = req.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return body[name]


def as_string(value, name):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return value


def as_enum(value, name, domain):
    if not isinstance(value, str) or value not in domain:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, list(domain)))
    return value


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (name, maximum))
    return value


def as_number(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    if minimum is not None and value < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s" % (name, maximum))
    return value


def parse_datetime_field(value, name):
    """Parse an ISO-8601 datetime body field; bad format -> ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO-8601 string" % name)
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO-8601 instant" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)
