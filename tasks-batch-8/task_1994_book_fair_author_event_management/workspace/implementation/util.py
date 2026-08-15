"""Request-body validation, pagination, datetime and decimal helpers.

Implements the priority-7 request-shape rule (ERR_VALIDATION): missing
required fields, wrong types, invalid enums, out-of-range numbers, unknown
fields. All monetary math elsewhere uses the Decimal helpers defined here.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from flask import request

from db import fmt_dt
from errors import fail


# ---------------------------------------------------------------------------
# Decimal helpers (PRD section 2.7 rounding doctrine)
# ---------------------------------------------------------------------------

def D(x):
    return Decimal(str(x))


def rhu(dec):
    """Round half-up to whole cents, returning an int."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(dec):
    return int(dec.to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Datetime parsing / formatting
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 datetime string" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt_loose(text):
    """Internal-only parse of a value this server previously formatted."""
    t = text[:-1] + "+00:00" if text.endswith("Z") else text
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Request body handling and field validators
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON request body as a dict; {} when no body was sent."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def v_str(name, value):
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "%s must be a string" % name)
    return value


def v_int(minimum=None, maximum=None):
    def check(name, value):
        if not isinstance(value, int) or isinstance(value, bool):
            fail("ERR_VALIDATION", "%s must be an integer" % name)
        if minimum is not None and value < minimum:
            fail("ERR_VALIDATION", "%s must be >= %s" % (name, minimum))
        if maximum is not None and value > maximum:
            fail("ERR_VALIDATION", "%s must be <= %s" % (name, maximum))
        return value

    return check


def v_pct(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_VALIDATION", "%s must be a number" % name)
    if value < 0 or value > 1:
        fail("ERR_VALIDATION", "%s must be between 0 and 1 inclusive" % name)
    return value


def v_enum(*values):
    def check(name, value):
        if not isinstance(value, str) or value not in values:
            fail("ERR_VALIDATION", "%s must be one of %s" % (name, "/".join(values)))
        return value

    return check


def v_datetime(name, value):
    return parse_dt(value, name)


def v_date(name, value):
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        fail("ERR_VALIDATION", "%s must be an ISO date (YYYY-MM-DD)" % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        fail("ERR_VALIDATION", "%s must be an ISO date (YYYY-MM-DD)" % name)
    return value


def validate_body(data, fields):
    """Validate a request body against [(name, required, validator), ...].

    Unknown fields are rejected. Validated values are returned keyed by name;
    absent optional fields are simply not present in the result.
    """
    allowed = {name for name, _, _ in fields}
    unknown = sorted(set(data.keys()) - allowed)
    if unknown:
        fail("ERR_VALIDATION", "Unknown field(s): %s" % ", ".join(unknown))
    out = {}
    for name, required, validator in fields:
        if name not in data or data[name] is None:
            if required:
                fail("ERR_VALIDATION", "Missing required field: %s" % name)
            continue
        out[name] = validator(name, data[name])
    return out


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def list_filtered(store, filters):
    """Entities sorted by created_at ASC, with equality filters applied.

    filters: list of (query_param, entity_field) pairs.
    """
    items = sorted(store.values(), key=lambda e: e["created_at"])
    for param, field in filters:
        raw = request.args.get(param)
        if raw is not None:
            items = [e for e in items if str(e.get(field)) == raw]
    return items


def page(items, limit, offset):
    return items[offset:offset + limit], len(items)
