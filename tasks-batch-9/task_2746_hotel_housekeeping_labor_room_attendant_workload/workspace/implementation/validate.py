"""Rung 4 of the precedence ladder -- request-body shape on every write operation.

PRD 2.10: every required input field present, every JSON type correct, every enum
value inside its declared set, counts and minute totals non-negative, inspection
point fields inside 0 through 10, and the expected_roster_version /
expected_linen_item_version field present on the two operations that declare it.
Any failure is ERR_INVALID_REQUEST (HTTP 400).
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from numeric import round_half_up
from timeutil import parse_iso_date, parse_iso_datetime


_MISSING = object()


def _bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def read_body(required=True):
    """Parse the JSON body.  A malformed body is a request-shape failure."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise _bad("Request body must be a JSON object.")
    if not isinstance(body, dict):
        raise _bad("Request body must be a JSON object.")
    return body


def _present(body, key):
    return key in body and body[key] is not None


def vstr(body, key, min_len=1, max_len=None, required=True, default=None, upper=False):
    if not _present(body, key):
        if key in body and body[key] is None and not required:
            return default
        if required:
            raise _bad("Field %s is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise _bad("Field %s must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise _bad("Field %s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise _bad("Field %s must be at most %d characters." % (key, max_len))
    if upper and value != value.upper():
        raise _bad("Field %s must be uppercase." % key)
    return value


def vint(body, key, lo=None, hi=None, required=True, default=None):
    if not _present(body, key):
        if required:
            raise _bad("Field %s is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad("Field %s must be an integer." % key)
    if lo is not None and value < lo:
        raise _bad("Field %s must be at least %s." % (key, lo))
    if hi is not None and value > hi:
        raise _bad("Field %s must be at most %s." % (key, hi))
    return value


def vdec(body, key, lo=None, hi=None, places=2, required=True, default=None):
    if not _present(body, key):
        if required:
            raise _bad("Field %s is required." % key)
        return default
    value = body[key]
    if isinstance(value, bool):
        raise _bad("Field %s must be a number." % key)
    if isinstance(value, str):
        # A decimal quantity may arrive in its exact string form -- "16.00" -- which is
        # how a caller preserves the two-decimal precision the PRD demands.
        try:
            value = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise _bad("Field %s must be a number." % key)
        if not value.is_finite():
            raise _bad("Field %s must be a number." % key)
    elif not isinstance(value, (int, float, Decimal)):
        raise _bad("Field %s must be a number." % key)
    quantised = round_half_up(value, places)
    if lo is not None and quantised < Decimal(str(lo)):
        raise _bad("Field %s must be at least %s." % (key, lo))
    if hi is not None and quantised > Decimal(str(hi)):
        raise _bad("Field %s must be at most %s." % (key, hi))
    return quantised


def vbool(body, key, required=False, default=False):
    if not _present(body, key):
        if required:
            raise _bad("Field %s is required." % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise _bad("Field %s must be a boolean." % key)
    return value


def venum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            raise _bad("Field %s is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise _bad("Field %s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def vdate(body, key, required=True, default=None, nullable=False):
    """Plain YYYY-MM-DD calendar date (PRD 2.4)."""
    if key not in body or body[key] is None:
        if key in body and body[key] is None and nullable:
            return None
        if required:
            raise _bad("Field %s is required." % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise _bad("Field %s must be a YYYY-MM-DD date string." % key)
    parsed = parse_iso_date(value)
    if parsed is None:
        raise _bad("Field %s must be a YYYY-MM-DD date string." % key)
    return parsed


def vdatetime(body, key, required=True, default=None, nullable=True):
    """ISO 8601 UTC instant (PRD 2.4)."""
    if key not in body or body[key] is None:
        if key in body and body[key] is None and nullable:
            return None
        if required:
            raise _bad("Field %s is required." % key)
        return default
    value = body[key]
    parsed = parse_iso_datetime(value)
    if parsed is None:
        raise _bad("Field %s must be an ISO 8601 UTC instant." % key)
    return parsed


def has_key(body, key):
    return key in body
