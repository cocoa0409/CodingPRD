"""Payload shape, enum membership, numeric range and interval helpers.

These implement steps 4 through 9 of the rejection ladder in PRD 2.10.  Each
helper performs exactly one step so that a route can run them in the fixed
order.
"""

from datetime import date, datetime, timezone

from flask import request

from errors import fail


# ------------------------------------------------------------------ step 4
def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _type_ok(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "array":
        return isinstance(value, list)
    return True


def required(b, name, kind):
    if name not in b or b[name] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = b[name]
    if not _type_ok(value, kind):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be of type %s." % (name, kind))
    return value


def optional(b, name, kind, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not _type_ok(value, kind):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be of type %s." % (name, kind))
    return value


def as_float(value):
    if value is None:
        return None
    return float(value)


# ------------------------------------------------------------------ step 5
def check_enum(name, value, vocabulary):
    if value is None:
        return value
    if value not in vocabulary:
        fail("ERR_INVALID_ENUM_VALUE",
             "Field '%s' must be one of %s." % (name, ", ".join(sorted(vocabulary))))
    return value


# ------------------------------------------------------------------ step 6
def check_min(name, value, minimum):
    if value is None:
        return value
    if value < minimum:
        fail("ERR_VALUE_OUT_OF_RANGE", "Field '%s' must be at least %s." % (name, minimum))
    return value


def check_range(name, value, minimum, maximum):
    if value is None:
        return value
    if value < minimum or value > maximum:
        fail("ERR_VALUE_OUT_OF_RANGE",
             "Field '%s' must lie between %s and %s." % (name, minimum, maximum))
    return value


def check_pct(name, value):
    return check_range(name, value, 0.0, 100.0)


def check_fee_pct(name, value):
    """Strictly above 0.0 and no greater than 100.0."""
    if value is None:
        return value
    if value <= 0.0 or value > 100.0:
        fail("ERR_VALUE_OUT_OF_RANGE",
             "Field '%s' must be above 0.0 and at most 100.0." % name)
    return value


def check_weight(name, value):
    """Strictly above 0.0 and no greater than 1.0."""
    if value is None:
        return value
    if value <= 0.0 or value > 1.0:
        fail("ERR_VALUE_OUT_OF_RANGE",
             "Field '%s' must be above 0.0 and at most 1.0." % name)
    return value


# --------------------------------------------------------------- date parsing
def parse_date(value, name):
    if value is None:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 date." % name)
    text = value.strip()
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, IndexError):
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)


def parse_dt(value, name):
    if value is None:
        return None
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ------------------------------------------------------------------ step 7
def check_interval_after(later, earlier, message):
    if later is None or earlier is None:
        return
    if not later > earlier:
        fail("ERR_INVALID_INTERVAL", message)


def check_interval_on_or_after(later, earlier, message):
    if later is None or earlier is None:
        return
    if later < earlier:
        fail("ERR_INVALID_INTERVAL", message)
