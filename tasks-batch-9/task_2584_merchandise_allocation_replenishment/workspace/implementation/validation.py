"""Request-shape validation (validation rung 4 -> ERR_INVALID_REQUEST 400)."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

MISSING = object()


def bad(msg="The request body or query parameters are malformed."):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    """Parse the JSON body.  A malformed or non-object body is a 400."""
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def present(data, name):
    return name in data


def _fetch(data, name, required):
    if name not in data or data[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return MISSING
    return data[name]


def get_str(data, name, required=True, default=None):
    v = _fetch(data, name, required)
    if v is MISSING:
        return default
    if not isinstance(v, str) or v.strip() == "":
        bad("Field '%s' must be a non-empty string." % name)
    return v


def get_int(data, name, required=True, default=None, minimum=None, maximum=None):
    v = _fetch(data, name, required)
    if v is MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))
    return v


def get_enum(data, name, allowed, required=True, default=None):
    v = _fetch(data, name, required)
    if v is MISSING:
        return default
    if not isinstance(v, str) or v not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return v


def get_money(data, name, required=True, default=None, minimum=None):
    v = _fetch(data, name, required)
    if v is MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        bad("Field '%s' must be a monetary number." % name)
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a monetary number." % name)
    if not d.is_finite():
        bad("Field '%s' must be a monetary number." % name)
    if -d.as_tuple().exponent > 2:
        bad("Field '%s' must carry at most 2 decimal places." % name)
    if minimum is not None and d < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (name, minimum))
    return d.quantize(Decimal("0.01"))


def parse_dt(value, name="value"):
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be an ISO 8601 UTC datetime." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 UTC datetime." % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_dt(data, name, required=True, default=None):
    v = _fetch(data, name, required)
    if v is MISSING:
        return default
    return parse_dt(v, name)


def get_list(data, name, required=True, default=None):
    v = _fetch(data, name, required)
    if v is MISSING:
        return default
    if not isinstance(v, list):
        bad("Field '%s' must be an array." % name)
    return v


def get_size_array(data, name, required=True):
    """Parse an array of { size_code, units } entries."""
    raw = get_list(data, name, required=required)
    if raw is None:
        return None
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            bad("Each entry of '%s' must be an object." % name)
        code = entry.get("size_code")
        units = entry.get("units")
        if not isinstance(code, str) or code.strip() == "":
            bad("Each entry of '%s' needs a size_code string." % name)
        if isinstance(units, bool) or not isinstance(units, int) or units < 0:
            bad("Each entry of '%s' needs a non-negative integer units." % name)
        out.append({"size_code": code, "units": units})
    return out


def get_size_curve(data, name):
    raw = get_list(data, name, required=True)
    if len(raw) < 1:
        bad("Field '%s' must contain at least one entry." % name)
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            bad("Each entry of '%s' must be an object." % name)
        code = entry.get("size_code")
        share = entry.get("share_bp")
        if not isinstance(code, str) or code.strip() == "":
            bad("Each entry of '%s' needs a size_code string." % name)
        if isinstance(share, bool) or not isinstance(share, int) or share < 0:
            bad("Each entry of '%s' needs a non-negative integer share_bp." % name)
        out.append({"size_code": code, "share_bp": share})
    return out


# --- query parameters ---------------------------------------------------------
def q_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def q_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.strip() == "":
        bad("Query parameter '%s' must be non-empty." % name)
    return raw


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw


def pagination():
    limit = q_int("limit", 10, 1, 100)
    offset = q_int("offset", 0, 0, None)
    return limit, offset


def page(records):
    limit, offset = pagination()
    total = len(records)
    chunk = records[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(chunk) < total,
    }
    return chunk, meta
