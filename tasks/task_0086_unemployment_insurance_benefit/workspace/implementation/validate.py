"""Input validation, parsing, pagination, OCC, and serialization helpers.

Validation ordering (PRD §2.10):
  auth -> role -> existence(404) -> reference(422) -> field-shape(400)
  -> uniqueness(409) -> state(409) -> business rules -> OCC.
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

_QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SSN_RE = re.compile(r"^\d{4}$")

# Internal bookkeeping keys excluded from serialized output.
_INTERNAL = {"_seq"}


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON body as a dict; {} if empty.

    A malformed (non-object) JSON body is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


# ---------------------------------------------------------------------------
# Typed field checks (ERR_INVALID_REQUEST on failure)
# ---------------------------------------------------------------------------
def as_string(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % name)
    return v


def as_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (name, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (name, maximum))
    return v


def as_number(body, name, required=True, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % name)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (name, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (name, maximum))
    return v


def as_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return v


def as_enum(body, name, choices, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    v = body[name]
    if v not in choices:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (name, sorted(choices)))
    return v


def validate_quarter(value):
    if not isinstance(value, str) or not _QUARTER_RE.match(value):
        raise err("ERR_INVALID_REQUEST", "calendar_quarter must match YYYY-Q[1-4].")
    return value


def validate_iso_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise err("ERR_INVALID_REQUEST", "%s must be an ISO date YYYY-MM-DD." % field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "%s is not a valid date." % field)


def validate_ssn_last4(value):
    if not isinstance(value, str) or not _SSN_RE.match(value):
        raise err("ERR_INVALID_REQUEST", "ssn_last4 must be exactly 4 numeric characters.")
    return value


def validate_saturday(value, field="week_ending_date"):
    d = validate_iso_date(value, field)
    # Monday=0 .. Saturday=5, Sunday=6
    if d.weekday() != 5:
        raise err("ERR_INVALID_REQUEST", "%s must be a Saturday." % field)
    return d


# ---------------------------------------------------------------------------
# Quarter helpers
# ---------------------------------------------------------------------------
def quarter_key(q):
    """(year, quarter_number) sort key from a 'YYYY-Q[1-4]' string."""
    year = int(q[:4])
    qn = int(q[6])
    return (year, qn)


def quarter_of_date(d):
    """Return (year, quarter_number) for a date."""
    return (d.year, (d.month - 1) // 3 + 1)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(records):
    """Sort by created_at ASC (tie-break by insertion seq) and page."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Optimistic concurrency (PRD §2.6)
# ---------------------------------------------------------------------------
def check_occ(body, field, record, error_id, required=False):
    """Compare expected_<x>_version against record['version'].

    When the field is present, mismatch -> error_id (412).
    When required and absent -> ERR_INVALID_REQUEST.
    When optional and absent -> no check.
    """
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return
    expected = body[field]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    if expected != record["version"]:
        raise err(error_id, "Version mismatch on %s." % field)


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.7)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half-up. Returns int."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_dollar(cents):
    """Round a cents value to the nearest whole dollar (multiple of 100), half-up."""
    dollars = Decimal(cents) / Decimal(100)
    whole = dollars.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(whole) * 100


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(record):
    """Return a public copy of a record (strip internal keys)."""
    return {k: v for k, v in record.items() if k not in _INTERNAL}
