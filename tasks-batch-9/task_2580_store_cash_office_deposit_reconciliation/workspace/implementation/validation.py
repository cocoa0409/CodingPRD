"""Request body shape validation (PRD section 2.12 step 3 / section 2.10)."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import bad_request

ALLOWED_DENOMINATIONS = (2000, 1000, 500, 100, 25, 10, 5, 1)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    """Returns the parsed JSON body, or {} when the request carries no body."""
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise bad_request("request body must be valid JSON")
    if not isinstance(parsed, dict):
        raise bad_request("request body must be a JSON object")
    return parsed


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_present(data, field):
    if field not in data or data[field] is None:
        raise bad_request("%s is required" % field)
    return data[field]


def req_int(data, field, minimum=0, maximum=None):
    value = req_present(data, field)
    if not is_int(value):
        raise bad_request("%s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be at least %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be at most %s" % (field, maximum))
    return value


def opt_int(data, field, default=None, minimum=0, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_str(data, field):
    value = req_present(data, field)
    if not isinstance(value, str) or value.strip() == "":
        raise bad_request("%s must be a non-empty string" % field)
    return value


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        raise bad_request("%s must be a string" % field)
    return value


def req_bool(data, field):
    value = req_present(data, field)
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean" % field)
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_bool(data, field)


def req_enum(data, field, members):
    value = req_str(data, field)
    if value not in members:
        raise bad_request("%s must be one of %s" % (field, ", ".join(members)))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, members)


def req_date(data, field):
    value = req_str(data, field)
    if not DATE_RE.match(value):
        raise bad_request("%s must be an ISO calendar date (YYYY-MM-DD)" % field)
    try:
        year, month, day = (int(part) for part in value.split("-"))
        import datetime as _dt

        _dt.date(year, month, day)
    except (ValueError, TypeError):
        raise bad_request("%s must be an ISO calendar date (YYYY-MM-DD)" % field)
    return value


def req_datetime(data, field):
    value = req_str(data, field)
    parsed = clock.parse(value)
    if parsed is None:
        raise bad_request("%s must be an ISO 8601 instant" % field)
    return parsed


def opt_datetime(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_datetime(data, field)


def req_number(data, field, minimum=None, maximum=None):
    value = req_present(data, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be a number" % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise bad_request("%s must be a number" % field)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise bad_request("%s must be at least %s" % (field, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise bad_request("%s must be at most %s" % (field, maximum))
    return dec


def opt_number(data, field, default=Decimal("0"), minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_number(data, field, minimum=minimum, maximum=maximum)


def req_counted_lines(data, field="counted_lines"):
    value = req_present(data, field)
    return _counted_lines(value, field)


def opt_counted_lines(data, field="counted_lines", default=None):
    if field not in data or data[field] is None:
        return default if default is not None else []
    return _counted_lines(data[field], field)


def _counted_lines(value, field):
    if not isinstance(value, list):
        raise bad_request("%s must be an array of denomination lines" % field)
    lines = []
    for entry in value:
        if not isinstance(entry, dict):
            raise bad_request("each %s entry must be an object" % field)
        denom = entry.get("denomination_cents")
        quantity = entry.get("quantity")
        if not is_int(denom) or denom not in ALLOWED_DENOMINATIONS:
            raise bad_request(
                "denomination_cents must be one of %s"
                % ", ".join(str(d) for d in ALLOWED_DENOMINATIONS)
            )
        if not is_int(quantity) or quantity < 0:
            raise bad_request("quantity must be an integer of at least 0")
        lines.append({"denomination_cents": denom, "quantity": quantity})
    return lines


def lines_value(lines):
    return sum(line["denomination_cents"] * line["quantity"] for line in (lines or []))


def req_id_list(data, field):
    value = req_present(data, field)
    if not isinstance(value, list) or len(value) == 0:
        raise bad_request("%s must be a non-empty array of identifiers" % field)
    for entry in value:
        if not isinstance(entry, str) or entry.strip() == "":
            raise bad_request("%s entries must be non-empty strings" % field)
    return list(value)
