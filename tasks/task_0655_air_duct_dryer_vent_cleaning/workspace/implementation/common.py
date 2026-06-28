"""Shared helpers: validation primitives, pagination, rounding, month math."""
import calendar
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err


# --------------------------------------------------------------------------
# Request body
# --------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if no body)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def as_int(body, field, *, required=True, default=None, minimum=None,
           maximum=None, exclusive_max=None):
    """Read an integer field with bounds. bool is not an int here."""
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s below minimum." % field)
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s above maximum." % field)
    if exclusive_max is not None and v >= exclusive_max:
        raise err("ERR_INVALID_REQUEST", "Field %s out of range." % field)
    return v


def as_number(body, field, *, required=True, default=None, minimum=None,
              maximum=None):
    """Read a numeric (int/float) field with inclusive bounds."""
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s below minimum." % field)
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s above maximum." % field)
    return v


def as_str(body, field, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    return v


def as_bool(body, field, *, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# --------------------------------------------------------------------------
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ascending (tie-break by insertion seq), then slice."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# --------------------------------------------------------------------------
# Rounding (PRD §2.7): round half up.
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest integer, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Month arithmetic for reminder cadence (calc next_reminder_advance).
# add_months clamps day-of-month to the last valid day of the target month.
# --------------------------------------------------------------------------
def add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)
