"""Payload shape validation — step 8 of the ladder in PRD §2.10.

Every helper raises `ERR_INVALID_REQUEST` (HTTP 400) on a shape problem. Foreign-key
*resolution* is step 7 and lives in `services.domain`; the helpers here only check that
an identifier is syntactically usable.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from clockutil import parse_date, parse_datetime, valid_month_day
from errors import ApiError


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """The JSON body as a dict; an absent body is an empty dict."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        bad("Request body must be a JSON object.")
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _missing(body, name):
    return name not in body or body[name] is None


def id_field(body, name, required=True):
    """A foreign-key identifier. Shape only — resolution happens separately."""
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return None
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a non-empty string." % name)
    return value


def str_field(body, name, required=True, default=None, min_len=1, max_len=None):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def int_field(body, name, required=True, default=None, minimum=None, maximum=None):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s." % (name, maximum))
    return value


def num_field(
    body,
    name,
    required=True,
    default=None,
    minimum=None,
    maximum=None,
    exclusive_minimum=None,
    places=None,
):
    """A decimal number. Returns `Decimal` so no float noise reaches a calculation."""
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number." % name)
    if not number.is_finite():
        bad("%s must be a finite number." % name)
    if minimum is not None and number < Decimal(str(minimum)):
        bad("%s must be at least %s." % (name, minimum))
    if maximum is not None and number > Decimal(str(maximum)):
        bad("%s must be at most %s." % (name, maximum))
    if exclusive_minimum is not None and number <= Decimal(str(exclusive_minimum)):
        bad("%s must be greater than %s." % (name, exclusive_minimum))
    if places is not None:
        number = number.quantize(Decimal(1).scaleb(-places))
    return number


def bool_field(body, name, required=False, default=None):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def enum_field(body, name, members, required=True, default=None):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in members:
        bad("%s must be one of %s." % (name, ", ".join(members)))
    return value


def enum_array_field(body, name, members, required=True, default=None, non_empty=True, distinct=True):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if non_empty and len(value) == 0:
        bad("%s may not be empty." % name)
    for member in value:
        if not isinstance(member, str) or member not in members:
            bad("%s members must be drawn from %s." % (name, ", ".join(members)))
    if distinct and len(set(value)) != len(value):
        bad("%s members must be distinct." % name)
    return list(value)


def date_field(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    parsed = parse_date(body[name])
    if parsed is None:
        bad("%s must be a calendar date formatted YYYY-MM-DD." % name)
    return parsed


def datetime_field(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    parsed = parse_datetime(body[name])
    if parsed is None:
        bad("%s must be a well formed ISO 8601 timestamp." % name)
    return parsed


def month_day_field(body, name, required=False, default=None):
    if _missing(body, name):
        if required:
            bad("%s is required." % name)
        return default
    value = body[name]
    if not valid_month_day(value):
        bad("%s must be formatted MM-DD." % name)
    return value.strip()


def email_field(body, name, required=True):
    value = str_field(body, name, required=required, min_len=1, max_len=320)
    if value is not None and "@" not in value:
        bad("%s must contain an at-sign." % name)
    return value


def state_code_field(body, name, required=True):
    value = str_field(body, name, required=required, min_len=2, max_len=2)
    if value is not None and not (value.isalpha() and value.isupper()):
        bad("%s must be exactly two uppercase letters." % name)
    return value
