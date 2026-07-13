"""Request-shape validation (PRD 2.6 step 3 -> ERR_INVALID_REQUEST)."""

from datetime import datetime, timezone

from flask import request

from errors import fail

SENTINEL = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def parse_dt(value, name):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp string." % name)
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _present(data, name, required):
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return False
    return True


def string(data, name, required=True, default=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def number(data, name, required=True, default=None, gt=None, ge=None, le=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    value = float(value)
    if gt is not None and not value > gt:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (name, gt))
    if ge is not None and not value >= ge:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, ge))
    if le is not None and not value <= le:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, le))
    return value


def integer(data, name, required=True, default=None, ge=None, le=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if ge is not None and value < ge:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, ge))
    if le is not None and value > le:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, le))
    return value


def boolean(data, name, required=True, default=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def enum(data, name, allowed, required=True, default=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))),
        )
    return value


def datetime_field(data, name, required=True, default=None):
    if not _present(data, name, required):
        return default
    return parse_dt(data[name], name)


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))),
        )
    return value


def query_dt(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return parse_dt(value, name)


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
