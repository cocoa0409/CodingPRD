"""Request body / query validation (validation priority 4: ERR_INVALID_REQUEST)."""
from datetime import datetime, timezone

from flask import request

from errors import ApiError

INDUSTRIES = ("RETAIL", "FINANCE", "CPG", "TECH", "AUTO")
GRADES = ("JUNIOR", "SENIOR", "DIRECTOR")
CHANNELS = ("DISPLAY", "VIDEO", "SOCIAL", "OOH", "PRINT")
OBJECTIVES = ("AWARENESS", "CONSIDERATION", "CONVERSION")
VENDOR_TYPES = ("FREELANCER", "PRODUCTION", "PRINT", "OTHER")
BILLING_MODES = ("PROVISIONAL", "FINAL")


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _present(b, key, required):
    if key not in b or b[key] is None:
        if required:
            bad("Missing required field '%s'." % key)
        return False
    return True


def req_str(b, key, required=True, max_len=None, default=None):
    if not _present(b, key, required):
        return default
    v = b[key]
    if not isinstance(v, str) or not v.strip():
        bad("Field '%s' must be a non-empty string." % key)
    if max_len is not None and len(v) > max_len:
        bad("Field '%s' exceeds %d characters." % (key, max_len))
    return v


def req_int(b, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(b, key, required):
        return default
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return v


def req_num(b, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(b, key, required):
        return default
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad("Field '%s' must be a number." % key)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return v


def req_bool(b, key, required=True, default=None):
    if not _present(b, key, required):
        return default
    v = b[key]
    if not isinstance(v, bool):
        bad("Field '%s' must be a boolean." % key)
    return v


def req_enum(b, key, members, required=True, default=None):
    if not _present(b, key, required):
        return default
    v = b[key]
    if not isinstance(v, str) or v not in members:
        bad("Field '%s' must be one of %s." % (key, ", ".join(members)))
    return v


def req_channels(b, key, required=True):
    if not _present(b, key, required):
        return None
    v = b[key]
    if not isinstance(v, list) or len(v) == 0:
        bad("Field '%s' must be a non-empty array." % key)
    for m in v:
        if not isinstance(m, str) or m not in CHANNELS:
            bad("Field '%s' members must be drawn from %s." % (key, ", ".join(CHANNELS)))
    return v


def parse_dt(value, key):
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an ISO 8601 string." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' is not a valid ISO 8601 instant." % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(b, key, required=True, default=None):
    if not _present(b, key, required):
        return default
    return parse_dt(b[key], key)


def req_date(b, key, required=True, default=None):
    if not _present(b, key, required):
        return default
    return parse_dt(b[key], key).date()


# --- query params -----------------------------------------------------------
def pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0 (PRD 2.3)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_date(name, required=True):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            bad("Missing required query parameter '%s'." % name)
        return None
    return parse_dt(raw, name).date()
