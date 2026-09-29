"""Structural request-body validation (rejection order item 4) plus small
numeric helpers used by the calculation modules."""

import re
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import request

from db import parse_date, parse_dt
from errors import ApiError

getcontext().prec = 60

_TERRITORY_RE = re.compile(r"^[A-Z]{2}$")
_NORMALIZE_STRIP = re.compile(r"[^a-z0-9 ]")
_NORMALIZE_SPACES = re.compile(r" +")


def bad(message="The request body is structurally invalid."):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON body as a dict; a missing body is treated as {}."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


# --------------------------------------------------------------------------
# field readers
# --------------------------------------------------------------------------

def get_string(data, name, required=True, min_len=1, max_len=None, default=None,
               nullable=False):
    if name not in data or data[name] is None:
        if name in data and data[name] is None and (nullable or not required):
            return None
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must not be empty." % name)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def get_int(data, name, required=True, minimum=None, maximum=None, default=None,
            nullable=False):
    if name not in data or data[name] is None:
        if name in data and data[name] is None and (nullable or not required):
            return None
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (name, maximum))
    return value


def get_enum(data, name, domain, required=True, default=None, nullable=False):
    if name not in data or data[name] is None:
        if name in data and data[name] is None and (nullable or not required):
            return None
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in domain:
        bad("Field '%s' must be one of %s." % (name, ", ".join(domain)))
    return value


def get_bool(data, name, required=False, default=False):
    if name not in data or data[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def get_date(data, name, required=True, default=None):
    value = get_string(data, name, required=required, default=default)
    if value is None:
        return None
    if parse_date(value) is None:
        bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    return value


def get_datetime(data, name, required=True):
    value = get_string(data, name, required=required)
    if value is None:
        return None
    if parse_dt(value) is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % name)
    return value


def get_id(data, name, required=True, nullable=False):
    """A foreign key field: string, non empty."""
    return get_string(data, name, required=required, nullable=nullable, max_len=200)


def get_territory(data, name, required=True, allow_world=True):
    value = get_string(data, name, required=required)
    if value is None:
        return None
    if allow_world and value == "WORLD":
        return value
    if not _TERRITORY_RE.match(value):
        bad("Field '%s' must be two uppercase letters%s." %
            (name, " or the literal WORLD" if allow_world else ""))
    return value


def get_territory_set(data, name):
    if name not in data or data[name] is None:
        bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, list) or not value:
        bad("Field '%s' must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must contain only strings." % name)
    if value == ["WORLD"]:
        return list(value)
    if "WORLD" in value:
        bad("Field '%s' may not mix WORLD with concrete territory codes." % name)
    if len(value) > 250:
        bad("Field '%s' may contain at most 250 codes." % name)
    if len(set(value)) != len(value):
        bad("Field '%s' must contain distinct codes." % name)
    for item in value:
        if not _TERRITORY_RE.match(item):
            bad("Field '%s' entries must be two uppercase letters." % name)
    return list(value)


def get_string_list(data, name):
    if name not in data or data[name] is None:
        bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or not item:
            bad("Field '%s' must contain only non-empty strings." % name)
    return list(value)


# --------------------------------------------------------------------------
# arithmetic helpers (§2.6)
# --------------------------------------------------------------------------

def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) to a whole unit."""
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """Mathematical floor of numerator / denominator."""
    numerator = int(numerator)
    denominator = int(denominator)
    return numerator // denominator


def ceil_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    return -((-numerator) // denominator)


def normalize_text(value):
    """§3.1 normalization used by the metadata matcher."""
    if value is None:
        return None
    lowered = value.lower()
    stripped = _NORMALIZE_STRIP.sub("", lowered)
    collapsed = _NORMALIZE_SPACES.sub(" ", stripped)
    return collapsed.strip()


def territory_matches(territory_set, code):
    """WORLD is a wildcard that intersects every territory (§2.7)."""
    if not territory_set:
        return False
    return "WORLD" in territory_set or code in territory_set


def territory_sets_intersect(left, right):
    if "WORLD" in left or "WORLD" in right:
        return True
    return bool(set(left) & set(right))


def half_open_overlap(a_from, a_to, b_from, b_to):
    """[a_from, a_to) overlaps [b_from, b_to)?"""
    return a_from < b_to and b_from < a_to


def closed_overlap(a_from, a_to, b_from, b_to):
    """[a_from, a_to] overlaps or touches [b_from, b_to]?"""
    return a_from <= b_to and b_from <= a_to
