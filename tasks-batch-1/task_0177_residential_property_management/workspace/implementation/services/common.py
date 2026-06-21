"""Shared helpers: serialization, pagination, field validation, money rounding.

Serialization strips internal-only keys (those starting with "_") so the
response body never leaks the creation-order sequence.

All request-shape validation failures raise ERR_INVALID_REQUEST (422), per
PRD §2.6 / SCAFFOLD validation priority 5.
"""
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import errors
from errors import err

# Pagination defaults (PRD §2.3, SCAFFOLD §1.0)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def serialize(record):
    """Return a public copy of a record with internal keys removed."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


# --- Pagination -------------------------------------------------------------
def parse_pagination(args):
    """Parse limit/offset query params. Raises ERR_INVALID_REQUEST when out of
    range (limit 1..100, offset >= 0). Missing -> defaults."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise err(errors.ERR_INVALID_REQUEST, "limit out of range 1..100")

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (creation order via _seq tiebreak) and slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total


def filter_param(args, name):
    """Plain string list-filter query param. Missing -> None."""
    return args.get(name)


# --- Field validation -------------------------------------------------------
def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def require_string(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, "%s must be a non-empty string" % name)
    return val


def optional_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be a string" % name)
    return val


def require_int(body, name, minimum=None, maximum=None):
    """Required integer. Booleans are rejected (bool is a subclass of int)."""
    require_fields(body, [name])
    return _check_int(body[name], name, minimum, maximum)


def optional_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return _check_int(body[name], name, minimum, maximum)


def _check_int(val, name, minimum, maximum):
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    if maximum is not None and val > maximum:
        raise err(errors.ERR_INVALID_REQUEST, "%s must be <= %s" % (name, maximum))
    return val


def require_number(body, name, minimum=None, maximum=None):
    """Required number (int or float, not bool)."""
    require_fields(body, [name])
    return _check_number(body[name], name, minimum, maximum)


def optional_number(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return _check_number(body[name], name, minimum, maximum)


def _check_number(val, name, minimum, maximum):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be a number" % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    if maximum is not None and val > maximum:
        raise err(errors.ERR_INVALID_REQUEST, "%s must be <= %s" % (name, maximum))
    return val


def require_bool(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return val


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return val


def require_enum(body, name, allowed, default=None):
    """Enum with optional declared default; out-of-set value -> ERR_INVALID_REQUEST."""
    if name not in body or body[name] is None:
        if default is not None:
            return default
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    val = body[name]
    if val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST,
                  "%s must be one of %s" % (name, sorted(allowed)))
    return val


def require_iso_date(body, name):
    require_fields(body, [name])
    return _parse_iso_date(body[name], name)


def optional_iso_date(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return _parse_iso_date(body[name], name)


def _parse_iso_date(val, name):
    if not isinstance(val, str) or not _ISO_DATE_RE.match(val):
        raise err(errors.ERR_INVALID_REQUEST, "%s must be an ISO date YYYY-MM-DD" % name)
    try:
        date.fromisoformat(val)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, "%s is not a valid date" % name)
    return val


def parse_date(s):
    """Parse a validated YYYY-MM-DD string to a date object."""
    return date.fromisoformat(s)


def days_between(start_str, end_str):
    """Whole-day difference end - start (may be negative)."""
    return (parse_date(end_str) - parse_date(start_str)).days


def add_days(date_str, days):
    """Return ISO date string of date_str + days."""
    from datetime import timedelta
    return (parse_date(date_str) + timedelta(days=days)).isoformat()


# --- Money / rounding -------------------------------------------------------
def round_half_up_cents(cents_decimal):
    """Round a Decimal value of cents to a whole integer of cents, half-up."""
    return int(Decimal(cents_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_ratio_4dp(numerator, denominator):
    """Compute numerator/denominator rounded half-up to 4 decimal places,
    returned as a float."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def pct_of_cents(cents, pct):
    """cents * pct rounded half-up to whole cents (pct is a decimal fraction)."""
    return round_half_up_cents(Decimal(cents) * Decimal(str(pct)))
