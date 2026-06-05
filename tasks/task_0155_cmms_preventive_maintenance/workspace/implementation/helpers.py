"""Shared request-validation and parsing helpers.

These implement the structural checks of PRD §2.3 (pagination), §2.7
(precision) and §2.8 (request well-formedness) in one place so routes stay
thin.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


# --- Pagination (PRD §2.3) --------------------------------------------------
def parse_pagination():
    """Return (limit, offset). limit default 10, min 1, max 100; offset
    default 0, min 0. Out-of-range -> ERR_VALIDATION (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer.")
        if offset < 0:
            raise errors.validation("offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]


# --- Field validation (PRD §2.8) -------------------------------------------
def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request("Missing required field: %s." % field)
    return body[field]


def require_str(body, field, allow_empty=False):
    val = require(body, field)
    if not isinstance(val, str):
        raise errors.invalid_request("Field %s must be a string." % field)
    if not allow_empty and val.strip() == "":
        raise errors.invalid_request("Field %s must be non-empty." % field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request("Field %s must be a string." % field)
    return val


def require_int(body, field, minimum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s must be >= %s." % (field, minimum))
    return val


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s must be >= %s." % (field, minimum))
    return val


def require_number(body, field, gt=None, ge=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field %s must be a number." % field)
    if gt is not None and not (val > gt):
        raise errors.invalid_request("Field %s must be > %s." % (field, gt))
    if ge is not None and not (val >= ge):
        raise errors.invalid_request("Field %s must be >= %s." % (field, ge))
    return val


def opt_number(body, field, default=None, gt=None, ge=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field %s must be a number." % field)
    if gt is not None and not (val > gt):
        raise errors.invalid_request("Field %s must be > %s." % (field, gt))
    if ge is not None and not (val >= ge):
        raise errors.invalid_request("Field %s must be >= %s." % (field, ge))
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of %s." % (field, sorted(allowed)))
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of %s." % (field, sorted(allowed)))
    return val


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a boolean." % field)
    return val


# --- Datetime parsing -------------------------------------------------------
def parse_dt(value, field):
    """Parse an ISO 8601 datetime into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive values are treated as
    UTC. Raises ERR_INVALID_REQUEST on a non-parseable value.
    """
    if not isinstance(value, str):
        raise errors.invalid_request("Field %s must be an ISO 8601 datetime string." % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request("Field %s is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_dt(body, field):
    val = require(body, field)
    return parse_dt(val, field)


def opt_dt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return parse_dt(body[field], field)


# --- Rounding (PRD §2.7) ----------------------------------------------------
def round_half_up_2(value):
    """Round half-up to two decimal places, returning a float for JSON."""
    q = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    f = float(q)
    # Present whole values as 0.0-style floats; tests compare numerically so a
    # float is fine. Avoid -0.0.
    if f == 0:
        return 0.0
    return f
