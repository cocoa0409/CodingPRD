"""Body validation helpers — refusal rule 5, ERR_INVALID_REQUEST (400).

An unknown extra field is ignored, never rejected (PRD section 2.8).
"""
from decimal import Decimal

from flask import request

from datetimes import parse_dt
from errors import ApiError
from money import D

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body must be valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def forbid(data, name, reason):
    if name in data and data[name] is not None:
        bad("%s is forbidden here: %s" % (name, reason))


def get_string(data, name, required=True, allow_empty=False):
    if not present(data, name):
        if required:
            bad("%s is required." % name)
        return None
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if not allow_empty and value.strip() == "":
        bad("%s must be a non-empty string." % name)
    return value


def get_enum(data, name, allowed, required=True):
    value = get_string(data, name, required=required)
    if value is None:
        return None
    if value not in tuple(allowed):
        bad("%s must be one of %s." % (name, ", ".join(tuple(allowed))))
    return value


def get_bool(data, name, required=True, default=None):
    if not present(data, name):
        if required:
            bad("%s is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def get_int(data, name, required=True, default=None, minimum=None, maximum=None):
    if not present(data, name):
        if required:
            bad("%s is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (name, maximum))
    return value


def get_number(data, name, required=True, default=None, minimum=None,
               exclusive_minimum=None, maximum=None):
    if not present(data, name):
        if required:
            bad("%s is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad("%s must be a number." % name)
    dec = D(value)
    if minimum is not None and dec < D(minimum):
        bad("%s must be >= %s." % (name, minimum))
    if exclusive_minimum is not None and dec <= D(exclusive_minimum):
        bad("%s must be > %s." % (name, exclusive_minimum))
    if maximum is not None and dec > D(maximum):
        bad("%s must be <= %s." % (name, maximum))
    return dec


def get_datetime(data, name, required=True, default=None):
    """Returns (raw_text, parsed_datetime)."""
    if not present(data, name):
        if required:
            bad("%s is required." % name)
        return default, None
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 datetime string." % name)
    parsed = parse_dt(value)
    if parsed is None:
        bad("%s must be an ISO 8601 datetime string." % name)
    return value, parsed


def get_string_array(data, name, allowed, required=True):
    if not present(data, name):
        if required:
            bad("%s is required." % name)
        return None
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if len(value) == 0:
        bad("%s must be a non-empty array." % name)
    seen = []
    for item in value:
        if not isinstance(item, str):
            bad("%s entries must be strings." % name)
        if item not in tuple(allowed):
            bad("%s entries must be drawn from %s." % (name, ", ".join(tuple(allowed))))
        if item in seen:
            bad("%s must not repeat an entry." % name)
        seen.append(item)
    return list(value)


def get_cash_flows(data, name):
    """Array of { period_index: integer >= 1, amount_usd: number >= 0 }."""
    if not present(data, name):
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if len(value) == 0:
        bad("%s must be a non-empty array." % name)
    seen = set()
    flows = []
    for entry in value:
        if not isinstance(entry, dict):
            bad("%s entries must be objects." % name)
        idx = entry.get("period_index")
        if isinstance(idx, bool) or not isinstance(idx, int):
            bad("%s[].period_index must be an integer." % name)
        if idx < 1:
            bad("%s[].period_index must be >= 1." % name)
        if idx in seen:
            bad("%s[].period_index must be unique." % name)
        seen.add(idx)
        amount = entry.get("amount_usd")
        if amount is None:
            bad("%s[].amount_usd is required." % name)
        if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
            bad("%s[].amount_usd must be a number." % name)
        if D(amount) < 0:
            bad("%s[].amount_usd must be >= 0." % name)
        flows.append({"period_index": idx, "amount_usd": D(amount)})
    return flows
