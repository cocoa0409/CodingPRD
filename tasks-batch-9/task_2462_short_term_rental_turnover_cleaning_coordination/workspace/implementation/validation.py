"""Request-shape validation (PRD 2.5 gate 3) and pagination parsing (PRD 2.3)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import errors
from errors import fail

_MISSING = object()


def json_body():
    """Parsed JSON object body, or {} when no body was supplied.

    A body that is present but not a JSON object is a request-shape failure.
    """
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return parsed


def _present(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    return value


def req_string(body, name, allow_empty=False):
    value = _present(body, name)
    if value is _MISSING:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is required." % name)
    return _as_string(value, name, allow_empty)


def opt_string(body, name, default=None, allow_empty=True):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return _as_string(value, name, allow_empty)


def _as_string(value, name, allow_empty):
    if not isinstance(value, str):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must not be empty." % name)
    return value


def req_enum(body, name, allowed):
    value = req_string(body, name, allow_empty=False)
    if value not in allowed:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return req_enum(body, name, allowed)


def req_int(body, name, minimum=None, maximum=None):
    value = _present(body, name)
    if value is _MISSING:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is required." % name)
    return _as_int(value, name, minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return _as_int(value, name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_bool(body, name, default=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % name)
    return value


def opt_decimal(body, name, default=None, minimum=None, maximum=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
    if not number.is_finite():
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a finite number." % name)
    if minimum is not None and number < Decimal(str(minimum)):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and number > Decimal(str(maximum)):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s." % (name, maximum))
    return number


def parse_datetime(value, name):
    if not isinstance(value, str) or value.strip() == "":
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 UTC datetime string." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 UTC datetime string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(body, name):
    value = _present(body, name)
    if value is _MISSING:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' is required." % name)
    return parse_datetime(value, name)


def opt_datetime(body, name, default=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    return parse_datetime(value, name)


def opt_string_list(body, name, default=None, max_items=None):
    value = _present(body, name)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an array of strings." % name)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an array of non-empty strings." % name)
    if max_items is not None and len(value) > max_items:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' may hold at most %d entries." % (name, max_items))
    return value


def opt_restock_entries(body, name="restock_entries"):
    """None when omitted; otherwise a list of {supply_line_id, qty_used}."""
    value = _present(body, name)
    if value is _MISSING:
        return None
    if not isinstance(value, list):
        fail(errors.ERR_INVALID_REQUEST, "Field 'restock_entries' must be an array.")
    entries = []
    for raw in value:
        if not isinstance(raw, dict):
            fail(errors.ERR_INVALID_REQUEST, "Each restock entry must be an object.")
        line_id = raw.get("supply_line_id")
        if not isinstance(line_id, str) or line_id.strip() == "":
            fail(errors.ERR_INVALID_REQUEST, "Each restock entry needs a supply_line_id string.")
        qty = raw.get("qty_used")
        if isinstance(qty, bool) or not isinstance(qty, int):
            fail(errors.ERR_INVALID_REQUEST, "Each restock entry needs an integer qty_used.")
        if qty < 1:
            fail(errors.ERR_INVALID_REQUEST, "Each restock entry needs qty_used >= 1.")
        entries.append({"supply_line_id": line_id, "qty_used": qty})
    return entries


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = PAGINATION_DEFAULT_LIMIT
    else:
        limit_value = _query_int(limit, "limit")
        if limit_value < PAGINATION_MIN_LIMIT or limit_value > PAGINATION_MAX_LIMIT:
            fail(errors.ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100.")
    if offset is None or offset == "":
        offset_value = PAGINATION_DEFAULT_OFFSET
    else:
        offset_value = _query_int(offset, "offset")
        if offset_value < 0:
            fail(errors.ERR_INVALID_REQUEST, "Query parameter 'offset' must not be negative.")
    return limit_value, offset_value


def _query_int(raw, name):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' must be an integer." % name)


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def query_string(name):
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
    fail(errors.ERR_INVALID_REQUEST, "Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
