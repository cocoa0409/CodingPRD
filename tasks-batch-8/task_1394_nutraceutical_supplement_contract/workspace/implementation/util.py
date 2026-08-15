"""Validation, decimal math, datetime, and pagination helpers."""
import calendar
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND

# Enumerations (PRD section 3).
DOSAGE_FORMS = ("TABLET", "CAPSULE", "POWDER", "SOFTGEL", "LIQUID")
ALLERGEN_CLASSES = (
    "NONE", "GLUTEN", "MILK", "SOY", "EGG",
    "PEANUT", "TREE_NUT", "FISH", "SHELLFISH", "SESAME",
)
OVERAGE_BASES = ("THEORETICAL", "LABEL_CLAIM")
PROTOCOLS = ("REAL_TIME", "ACCELERATED")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
def invalid(message):
    raise_error(ERR_INVALID_REQUEST, message)


def not_found(message="Path identifier does not identify an existing resource"):
    raise_error(ERR_NOT_FOUND, message)


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    """Return the JSON request body as a dict; empty/missing body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object")
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value == "":
        invalid("'%s' must be a non-empty string" % field)
    return value


def req_enum(data, field, allowed):
    value = data.get(field)
    if value not in allowed:
        invalid("'%s' must be one of %s" % (field, list(allowed)))
    return value


def req_int(data, field, min_val=None):
    value = data.get(field)
    if not is_int(value):
        invalid("'%s' must be an integer" % field)
    if min_val is not None and value < min_val:
        invalid("'%s' must be at least %s" % (field, min_val))
    return value


def req_num(data, field):
    value = data.get(field)
    if not is_num(value):
        invalid("'%s' must be a number" % field)
    return value


# ---------------------------------------------------------------------------
# Decimal math (PRD section 2.7). Money stays integer cents; computed masses
# and percentages are rounded half-up to their pinned precision.
# ---------------------------------------------------------------------------
def dec(value):
    return Decimal(str(value))


def round2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round1(value):
    return dec(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def num_out(d):
    """Render a quantized Decimal as a JSON number (int when integral)."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Datetime parsing / formatting
# ---------------------------------------------------------------------------
def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        invalid("'%s' must be an ISO 8601 timestamp string" % field)
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        invalid("'%s' must be a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def last_day_of_month_after(year, month, months_to_add):
    """Last calendar day of (year, month) + months_to_add (PRD section 3.7)."""
    total = year * 12 + (month - 1) + months_to_add
    new_year, rem = divmod(total, 12)
    new_month = rem + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    return "%04d-%02d-%02d" % (new_year, new_month, last_day)


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit default 10, min 1, max 100; offset
# default 0. Lists are sorted by created_at ascending (stable on insertion
# order for identical logical-clock timestamps).
# ---------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        invalid("'limit' must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        invalid("'offset' must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sorted_by_created(items):
    return sorted(items, key=lambda e: e["created_at"])
