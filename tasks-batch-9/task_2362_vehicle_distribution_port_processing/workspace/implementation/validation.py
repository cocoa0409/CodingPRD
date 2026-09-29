"""Request body / query-string schema validation (PRD §2.3, §2.6 band 5)."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import invalid

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0

_MISSING = object()


def body():
    """The JSON request body as a dict; {} when the request carries no body."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None or not isinstance(parsed, dict):
        invalid("Request body must be a JSON object")
    return parsed


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        invalid("%s is required" % name)
    if not isinstance(value, str) or value.strip() == "":
        invalid("%s must be a non-empty string" % name)
    return value


def opt_str(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str):
        invalid("%s must be a string" % name)
    return value


def _as_int(value, name):
    if isinstance(value, bool):
        invalid("%s must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    invalid("%s must be an integer" % name)


def req_int(data, name, minimum=None, maximum=None):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        invalid("%s is required" % name)
    value = _as_int(value, name)
    if minimum is not None and value < minimum:
        invalid("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("%s must be <= %s" % (name, maximum))
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_enum(data, name, allowed):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        invalid("%s is required" % name)
    if not isinstance(value, str) or value not in allowed:
        invalid("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_rate(data, name, minimum, maximum, max_decimals):
    """A fractional rate: range-checked and limited in decimal places."""
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        invalid("%s is required" % name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("%s must be a number" % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        invalid("%s must be a number" % name)
    if dec < Decimal(str(minimum)) or dec > Decimal(str(maximum)):
        invalid("%s must be between %s and %s" % (name, minimum, maximum))
    exponent = dec.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -max_decimals:
        invalid("%s carries at most %d decimal places" % (name, max_decimals))
    return value


def parse_instant(value, name):
    if not isinstance(value, str) or value.strip() == "":
        invalid("%s must be an ISO 8601 instant" % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        invalid("%s must be an ISO 8601 instant" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_instant(data, name):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        invalid("%s is required" % name)
    return parse_instant(value, name)


def req_interval(data, start_name, end_name):
    start = req_instant(data, start_name)
    end = req_instant(data, end_name)
    if not end > start:
        invalid("%s must be strictly after %s" % (end_name, start_name))
    return start, end


def req_line_items(data, name="line_items"):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        invalid("%s is required" % name)
    if not isinstance(value, list) or len(value) < 1:
        invalid("%s must contain at least one damage line" % name)
    zones = ("GLASS", "BODY_PANEL", "INTERIOR", "UNDERBODY")
    normalized = []
    for line in value:
        if not isinstance(line, dict):
            invalid("each %s entry must be an object" % name)
        zone = req_enum(line, "damage_zone", zones)
        points = req_int(line, "severity_points", minimum=1, maximum=60)
        estimate = req_int(line, "repair_estimate_cents", minimum=0)
        normalized.append(
            {
                "damage_zone": zone,
                "severity_points": points,
                "repair_estimate_cents": estimate,
            }
        )
    return normalized


# ------------------------------------------------------------------ paging
def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            invalid("limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset must be >= 0")
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    invalid("%s must be true or false" % name)


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    window = records[offset : offset + limit]
    return [serializer(r) for r in window], limit, offset, total
