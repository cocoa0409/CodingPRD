"""Request-shape validation (PRD §2.10 tier 3) and pagination (PRD §2.3)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
from errors import ApiError

_MISSING = object()


def bad(msg):
    return ApiError("ERR_INVALID_REQUEST", msg)


def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None):
    if not _present(data, name):
        raise bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(data, name, min_len=1, max_len=None, default=None):
    if not _present(data, name):
        return default
    return req_str(data, name, min_len, max_len)


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        raise bad("Field '%s' is required." % name)
    return _as_int(data[name], name, minimum, maximum)


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    return _as_int(data[name], name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def req_number(data, name, minimum=None, maximum=None, exclusive_min=False):
    if not _present(data, name):
        raise bad("Field '%s' is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % name)
    if minimum is not None:
        if exclusive_min and not value > minimum:
            raise bad("Field '%s' must be > %s." % (name, minimum))
        if not exclusive_min and value < minimum:
            raise bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def req_bool(data, name):
    if not _present(data, name):
        raise bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    return req_bool(data, name)


def req_enum(data, name, values):
    value = req_str(data, name, 1, None)
    if value not in values:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(values)))
    return value


def opt_enum(data, name, values, default=None):
    if not _present(data, name):
        return default
    return req_enum(data, name, values)


def req_date(data, name):
    raw = req_str(data, name, 1, None)
    parsed = clock.parse_date_strict(raw)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    return raw, parsed


def opt_date(data, name):
    if not _present(data, name):
        return None, None
    return req_date(data, name)


def req_instant(data, name):
    raw = req_str(data, name, 1, None)
    parsed = clock.parse_instant(raw)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 instant." % name)
    return raw, parsed


def opt_id(data, name):
    if not _present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str) or not value:
        raise bad("Field '%s' must be a string identifier." % name)
    return value


def req_id(data, name):
    if not _present(data, name):
        raise bad("Field '%s' is required." % name)
    return opt_id(data, name)


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_enum(name, values):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(values)))
    return raw


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % name)


def paginate(items):
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


# ---------------------------------------------------------------------------
# Arithmetic helpers (PRD §2.8: round half up everywhere)
# ---------------------------------------------------------------------------

def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    return int(round_half_up(value, 0))


def ratio4(numerator, denominator):
    if denominator == 0:
        return None
    return float(round_half_up(Decimal(numerator) / Decimal(denominator), 4))


def dec(value):
    return Decimal(str(value))
