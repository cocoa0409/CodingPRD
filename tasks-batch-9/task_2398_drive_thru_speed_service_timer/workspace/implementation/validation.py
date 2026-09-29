"""Request-schema validation (PRD §2.11 step 6 -> ERR_INVALID_REQUEST 400)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from db import dec
from errors import invalid

ISO_WHOLE_SECOND = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(Z|\+00:00|\+0000)$"
)


def raw_body():
    """Lenient read used before the schema step (scope checks need body ids)."""
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    return {}


def body_or_400():
    if not request.get_data():
        return {}
    body = request.get_json(silent=True)
    if body is None:
        invalid("request body must be a JSON object")
    if not isinstance(body, dict):
        invalid("request body must be a JSON object")
    return body


# ------------------------------------------------------------------- primitives
def req_str(body, name):
    value = body.get(name)
    if not isinstance(value, str) or value.strip() == "":
        invalid("%s is required and must be a non-empty string" % name)
    return value


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        invalid("%s must be a non-empty string" % name)
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        invalid("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        invalid("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("%s must be an integer" % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        invalid("%s is required" % name)
    value = _as_int(name, body[name])
    _range_check(name, value, minimum, maximum)
    return value


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if name not in body or body[name] is None:
        return default
    value = _as_int(name, body[name])
    _range_check(name, value, minimum, maximum)
    return value


def _range_check(name, value, minimum, maximum):
    if minimum is not None and value < minimum:
        invalid("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("%s must be <= %s" % (name, maximum))


def _as_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        invalid("%s must be a number" % name)
    try:
        return dec(value)
    except (InvalidOperation, ValueError):
        invalid("%s must be a number" % name)


def req_num(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        invalid("%s is required" % name)
    value = _as_decimal(name, body[name])
    _range_check(name, value, minimum, maximum)
    return value


def opt_num(body, name, minimum=None, maximum=None, default=None):
    if name not in body or body[name] is None:
        return default
    value = _as_decimal(name, body[name])
    _range_check(name, value, minimum, maximum)
    return value


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        invalid("%s must be a boolean" % name)
    return value


def parse_dt(name, value):
    if not isinstance(value, str) or not ISO_WHOLE_SECOND.match(value):
        invalid("%s must be an ISO-8601 UTC timestamp with whole seconds" % name)
    text = value.replace("Z", "").replace("+00:00", "").replace("+0000", "")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        invalid("%s must be an ISO-8601 UTC timestamp with whole seconds" % name)
    return parsed.replace(tzinfo=timezone.utc)


def req_dt(body, name):
    if name not in body or body[name] is None:
        invalid("%s is required" % name)
    return parse_dt(name, body[name])


# ---------------------------------------------------------------- query filters
def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value.strip() == "":
        invalid("%s filter must be a non-empty string" % name)
    return value


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        invalid("%s must be one of %s" % (name, ", ".join(allowed)))
    return value
