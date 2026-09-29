"""Payload validation — priority 3 of the ladder (ERR_INVALID_REQUEST, 400).

Every helper raises ApiError('ERR_INVALID_REQUEST') so that a malformed payload
is always reported before any existence, ownership, OCC or state check runs.
"""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_MISSING = object()

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body(optional=True):
    """Parse the JSON body. A missing/empty body is an empty dict when every
    field of the endpoint is optional; malformed JSON is always invalid."""
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        if optional:
            return {}
        raise bad("request body is required")
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("request body is not valid JSON")
    if parsed is None:
        if optional:
            return {}
        raise bad("request body is required")
    if not isinstance(parsed, dict):
        raise bad("request body must be a JSON object")
    return parsed


def parse_dt(value, name="value"):
    if not isinstance(value, str):
        raise bad("%s must be an ISO-8601 datetime string" % name)
    text = value.strip()
    match = _DT_RE.match(text)
    if not match:
        raise bad("%s must be an ISO-8601 datetime string" % name)
    frac = match.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    if micro >= 1000000:
        micro = 999999
    tz_text = match.group(8)
    try:
        naive = datetime(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            int(match.group(5)),
            int(match.group(6)),
            micro,
        )
    except ValueError:
        raise bad("%s is not a real datetime" % name)
    if tz_text in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tz_text[0] == "+" else -1
    digits = tz_text[1:].replace(":", "")
    offset_minutes = sign * (int(digits[:2]) * 60 + int(digits[2:4]))
    aware = naive.replace(tzinfo=timezone.utc)
    return aware - _minutes(offset_minutes)


def _minutes(count):
    from datetime import timedelta

    return timedelta(minutes=count)


# --------------------------------------------------------------------------
# typed field readers
# --------------------------------------------------------------------------
def _present(data, name, required):
    if name not in data or data[name] is None:
        if required:
            raise bad("%s is required" % name)
        return _MISSING
    return data[name]


def field_str(data, name, required=True, default=None, allow_blank=False):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise bad("%s must be a string" % name)
    if not allow_blank and not value.strip():
        raise bad("%s must be a non-empty string" % name)
    return value


def field_int(data, name, required=True, default=None, minimum=None, maximum=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("%s must be <= %s" % (name, maximum))
    return value


def field_num(
    data,
    name,
    required=True,
    default=None,
    minimum=None,
    maximum=None,
    exclusive_min=None,
    exclusive_max=None,
):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("%s must be a number" % name)
    value = float(value)
    if minimum is not None and value < minimum:
        raise bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("%s must be <= %s" % (name, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        raise bad("%s must be > %s" % (name, exclusive_min))
    if exclusive_max is not None and value >= exclusive_max:
        raise bad("%s must be < %s" % (name, exclusive_max))
    return value


def field_bool(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        raise bad("%s must be a boolean" % name)
    return value


def field_enum(data, name, allowed, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def field_dt(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    return parse_dt(value, name)


def field_id(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or not value.strip():
        raise bad("%s must be a non-empty id string" % name)
    return value


def field_state_codes(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list) or not value:
        raise bad("%s must be a non-empty array" % name)
    out = []
    for item in value:
        if not isinstance(item, str) or len(item) != 2 or item != item.upper():
            raise bad("%s entries must be 2-character uppercase state codes" % name)
        out.append(item)
    return out


def field_crane_chart(data, name, required=True, default=None):
    """Ordered chart of { radius_ft, capacity_lb } with radius strictly ascending
    and capacity strictly descending (§1.1 Project.crane_capacity_chart)."""
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list) or not value:
        raise bad("%s must be a non-empty array" % name)
    chart = []
    previous = None
    for entry in value:
        if not isinstance(entry, dict):
            raise bad("%s entries must be objects" % name)
        radius = entry.get("radius_ft")
        capacity = entry.get("capacity_lb")
        for label, item in (("radius_ft", radius), ("capacity_lb", capacity)):
            if isinstance(item, bool) or not isinstance(item, int):
                raise bad("%s.%s must be an integer" % (name, label))
            if item < 0:
                raise bad("%s.%s must be >= 0" % (name, label))
        if previous is not None:
            if radius <= previous["radius_ft"]:
                raise bad("%s radius_ft must be strictly ascending" % name)
            if capacity >= previous["capacity_lb"]:
                raise bad("%s capacity_lb must be strictly descending" % name)
        entry_row = {"radius_ft": radius, "capacity_lb": capacity}
        chart.append(entry_row)
        previous = entry_row
    return chart


def field_str_query(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def enum_query(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value
