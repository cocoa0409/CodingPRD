"""Request-shape validation — ladder rung 3 (PRD §2.9.3). Always ERR_INVALID_REQUEST."""

from decimal import Decimal
from decimal import InvalidOperation

from flask import request

from errors import ApiError
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from timeutil import parse_dt


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict; an absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    # `force` so a JSON payload sent without the JSON content type still parses;
    # `silent` so a malformed payload becomes ERR_INVALID_REQUEST, not a 400 page.
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


# -- strings ---------------------------------------------------------------


def req_str(data, name, min_len=1, max_len=None):
    if not _present(data, name):
        bad("'%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        bad("'%s' must be a string." % name)
    if len(value) < min_len:
        bad("'%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("'%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(data, name, min_len=1, max_len=None, default=None):
    if not _present(data, name):
        return default
    return req_str(data, name, min_len, max_len)


def req_ref(data, name):
    """A required foreign-key string; existence is checked at rung 5."""
    if not _present(data, name):
        bad("'%s' is required." % name)
    value = data[name]
    if not isinstance(value, str) or not value:
        bad("'%s' must be a non-empty string identifier." % name)
    return value


def opt_ref(data, name, default=None):
    if not _present(data, name):
        return default
    return req_ref(data, name)


# -- integers --------------------------------------------------------------


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("'%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("'%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("'%s' must be at most %s." % (name, maximum))
    return value


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        bad("'%s' is required." % name)
    return _check_int(name, data[name], minimum, maximum)


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        return default
    return _check_int(name, data[name], minimum, maximum)


# -- decimals --------------------------------------------------------------


def _check_num(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad("'%s' must be a number." % name)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("'%s' must be a number." % name)
    if not number.is_finite():
        bad("'%s' must be a finite number." % name)
    if minimum is not None and number < Decimal(str(minimum)):
        bad("'%s' must be at least %s." % (name, minimum))
    if maximum is not None and number > Decimal(str(maximum)):
        bad("'%s' must be at most %s." % (name, maximum))
    return number


def req_num(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        bad("'%s' is required." % name)
    return _check_num(name, data[name], minimum, maximum)


def opt_num(data, name, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        return default
    return _check_num(name, data[name], minimum, maximum)


# -- booleans / enums / datetimes -----------------------------------------


def opt_bool(data, name, default=False):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("'%s' must be a boolean." % name)
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name, 1, None)
    if value not in allowed:
        bad("'%s' must be one of: %s." % (name, ", ".join(allowed)))
    return value


def req_dt(data, name):
    """Returns the raw client text; input instants are echoed back verbatim."""
    value = req_str(data, name, 1, None)
    if parse_dt(value) is None:
        bad("'%s' must be an ISO 8601 datetime." % name)
    return value


def opt_dt(data, name, default=None):
    if not _present(data, name):
        return default
    return req_dt(data, name)


# -- pagination ------------------------------------------------------------


def _query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = raw.strip()
    try:
        return int(text, 10)
    except (TypeError, ValueError):
        bad("'%s' must be an integer." % name)


def pagination():
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        bad(
            "'limit' must be between %d and %d."
            % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
        )
    if offset < 0:
        bad("'offset' must be at least 0.")
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def line_items(data, name="line_items"):
    """1..12 ordered entries; markup's 22.0 cap is rung 47, not rung 3."""
    if not _present(data, name):
        bad("'%s' is required." % name)
    value = data[name]
    if not isinstance(value, list):
        bad("'%s' must be an array." % name)
    if len(value) < 1 or len(value) > 12:
        bad("'%s' must hold between 1 and 12 elements." % name)
    parsed = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            bad("'%s[%d]' must be an object." % (name, index))
        label = "%s[%d]" % (name, index)
        description = item.get("description")
        if not isinstance(description, str) or not description:
            bad("'%s.description' must be a non-empty string." % label)
        quantity = item.get("quantity")
        _check_int("%s.quantity" % label, quantity, 1, None)
        unit_cost = item.get("unit_cost_cents")
        _check_int("%s.unit_cost_cents" % label, unit_cost, 0, None)
        markup = _check_num("%s.markup_pct" % label, item.get("markup_pct"), 0.0, None)
        is_taxable = item.get("is_taxable")
        if not isinstance(is_taxable, bool):
            bad("'%s.is_taxable' must be a boolean." % label)
        parsed.append(
            {
                "description": description,
                "quantity": quantity,
                "unit_cost_cents": unit_cost,
                "markup_pct": markup,
                "is_taxable": is_taxable,
            }
        )
    return parsed
