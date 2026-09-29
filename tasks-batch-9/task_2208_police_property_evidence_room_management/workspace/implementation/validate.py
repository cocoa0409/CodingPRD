"""Request-shape validation helpers (validation stage 6: ERR_INVALID_REQUEST)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("The request body must be a JSON object.")
    return data


def parse_dt(value, name):
    if not isinstance(value, str) or not value.strip():
        bad("%s must be an ISO 8601 timestamp string." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("%s must be an ISO 8601 timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_str(data, name, min_len=None, max_len=None, pattern=None):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("%s has an invalid format." % name)
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_int(data, name, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %d." % (name, maximum))
    return value


def req_bool(data, name):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def req_dt(data, name):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    return parse_dt(data[name], name)


def req_number(data, name, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    if minimum is not None and float(value) < minimum:
        bad("%s must be at least %s." % (name, minimum))
    if maximum is not None and float(value) > maximum:
        bad("%s must be at most %s." % (name, maximum))
    return value


def opt_str(data, name):
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    return value


def must_be_absent(data, name, reason):
    if name in data and data[name] is not None:
        bad("%s must be null %s." % (name, reason))


# --------------------------------------------------------------------------
# list filters
# --------------------------------------------------------------------------

def filter_rows(rows, spec):
    """spec maps query-parameter name -> (field name, kind)."""
    out = list(rows)
    for param, (field, kind) in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "bool":
            lowered = raw.strip().lower()
            if lowered in ("true", "1"):
                wanted = True
            elif lowered in ("false", "0"):
                wanted = False
            else:
                return []
            out = [r for r in out if bool(r.get(field)) is wanted]
        else:
            out = [r for r in out if r.get(field) == raw]
    return out
