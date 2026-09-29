"""Request-shape validation and entity lookups.

Two-pass field parsing keeps the rejection order of PRD 2.9 tier 6 intact:
every ``ERR_INVALID_REQUEST`` complaint is raised before any
``ERR_INVALID_ENUM_VALUE`` complaint.
"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import ApiError

MISSING = object()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGITS_RE = re.compile(r"^\d+$")
CODE_RE = re.compile(r"^[A-Z0-9-]+$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body_json():
    """The parsed JSON body, defaulting to an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("request body must be a JSON object")
    if not isinstance(payload, dict):
        bad("request body must be a JSON object")
    return payload


class Spec(object):
    __slots__ = ("name", "kind", "required", "default", "opts")

    def __init__(self, name, kind, required=True, default=MISSING, **opts):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.opts = opts


def S(name, kind, required=True, default=MISSING, **opts):
    return Spec(name, kind, required, default, **opts)


def parse_body(body, specs):
    out = {}
    # ---- pass 1: presence and non-enum shape (ERR_INVALID_REQUEST) ----
    for spec in specs:
        present = spec.name in body and body[spec.name] is not None
        if not present:
            if spec.required:
                bad("field '%s' is required" % spec.name)
            if spec.default is not MISSING:
                out[spec.name] = spec.default
            continue
        value = body[spec.name]
        if spec.kind == "enum":
            if not isinstance(value, str) or value.strip() == "":
                bad("field '%s' must be a string" % spec.name)
            out[spec.name] = value
        else:
            out[spec.name] = _parse_scalar(spec, value)
    # ---- pass 2: enum membership (ERR_INVALID_ENUM_VALUE) ----
    for spec in specs:
        if spec.kind != "enum":
            continue
        if spec.name not in out:
            continue
        value = out[spec.name]
        if value not in spec.opts["allowed"]:
            raise ApiError("ERR_INVALID_ENUM_VALUE",
                           "field '%s' does not accept value '%s'" % (spec.name, value))
    return out


def _parse_scalar(spec, value):
    kind = spec.kind
    opts = spec.opts
    if kind == "str":
        if not isinstance(value, str):
            bad("field '%s' must be a string" % spec.name)
        length = len(value)
        if "min_len" in opts and length < opts["min_len"]:
            bad("field '%s' is shorter than %d characters" % (spec.name, opts["min_len"]))
        if "max_len" in opts and length > opts["max_len"]:
            bad("field '%s' is longer than %d characters" % (spec.name, opts["max_len"]))
        if opts.get("pattern") is not None and not opts["pattern"].match(value):
            bad("field '%s' has an unacceptable format" % spec.name)
        return value
    if kind == "digits":
        if not isinstance(value, str) or not _DIGITS_RE.match(value):
            bad("field '%s' must contain digits only" % spec.name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("field '%s' must be an integer" % spec.name)
        if "min" in opts and value < opts["min"]:
            bad("field '%s' must be at least %d" % (spec.name, opts["min"]))
        if "max" in opts and value > opts["max"]:
            bad("field '%s' must be at most %d" % (spec.name, opts["max"]))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            bad("field '%s' must be a boolean" % spec.name)
        return value
    if kind == "dec2":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            bad("field '%s' must be a number" % spec.name)
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError):
            bad("field '%s' must be a number" % spec.name)
        if parsed != parsed.to_integral_value() and -parsed.as_tuple().exponent > 2:
            bad("field '%s' accepts at most two decimal places" % spec.name)
        if "min" in opts and parsed < Decimal(str(opts["min"])):
            bad("field '%s' is below the permitted minimum" % spec.name)
        if "max" in opts and parsed > Decimal(str(opts["max"])):
            bad("field '%s' is above the permitted maximum" % spec.name)
        return parsed.quantize(Decimal("0.01"))
    if kind == "date":
        return parse_date(value, spec.name)
    if kind == "datetime":
        return parse_instant(value, spec.name)
    raise AssertionError("unknown spec kind %r" % kind)


def parse_date(value, field="date"):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        bad("field '%s' must be a YYYY-MM-DD date" % field)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad("field '%s' is not a real calendar date" % field)


def parse_instant(value, field="timestamp"):
    if not isinstance(value, str) or value.strip() == "":
        bad("field '%s' must be an ISO 8601 UTC instant" % field)
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        bad("field '%s' must be an ISO 8601 UTC instant" % field)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    if parsed.utcoffset().total_seconds() != 0:
        bad("field '%s' must be a UTC instant" % field)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# entity lookups
# --------------------------------------------------------------------------

_NOT_FOUND = {
    "categories": "ERR_CATEGORY_NOT_FOUND",
    "stores": "ERR_STORE_NOT_FOUND",
    "vendors": "ERR_VENDOR_NOT_FOUND",
    "counter_firms": "ERR_COUNTER_FIRM_NOT_FOUND",
    "items": "ERR_ITEM_NOT_FOUND",
    "stock_positions": "ERR_STOCK_POSITION_NOT_FOUND",
    "tag_batches": "ERR_TAG_BATCH_NOT_FOUND",
    "count_schedules": "ERR_COUNT_SCHEDULE_NOT_FOUND",
    "count_tasks": "ERR_COUNT_TASK_NOT_FOUND",
    "count_lines": "ERR_COUNT_LINE_NOT_FOUND",
    "investigations": "ERR_INVESTIGATION_NOT_FOUND",
    "adjustments": "ERR_ADJUSTMENT_NOT_FOUND",
    "shrink_periods": "ERR_SHRINK_PERIOD_NOT_FOUND",
    "physical_inventories": "ERR_PHYSICAL_INVENTORY_NOT_FOUND",
    "physical_inventory_lines": "ERR_PHYSICAL_INVENTORY_LINE_NOT_FOUND",
}


def lookup(collection, entity_id):
    """Resolve an id or raise the collection's 404."""
    table = getattr(db, collection)
    if not isinstance(entity_id, str):
        raise ApiError(_NOT_FOUND[collection])
    row = table.get(entity_id)
    if row is None:
        raise ApiError(_NOT_FOUND[collection])
    return row


def lookup_body_fk(body, field, collection, required=True):
    """Body foreign keys resolve at tier 5, before request-shape checks."""
    if field not in body or body[field] is None:
        if required:
            return None
        return None
    return lookup(collection, body[field])


# --------------------------------------------------------------------------
# query-string filters
# --------------------------------------------------------------------------

def filter_enum(param, allowed):
    """Enumerated list filter; anything unenumerated -> ERR_INVALID_ENUM_VALUE."""
    raw = request.args.get(param)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_ENUM_VALUE",
                       "filter '%s' does not accept value '%s'" % (param, raw))
    return raw


def filter_bool(param):
    raw = request.args.get(param)
    if raw is None or raw == "":
        return None
    if raw not in ("true", "false"):
        raise ApiError("ERR_INVALID_ENUM_VALUE",
                       "filter '%s' does not accept value '%s'" % (param, raw))
    return raw == "true"


def filter_int(param):
    raw = request.args.get(param)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_ENUM_VALUE",
                       "filter '%s' does not accept value '%s'" % (param, raw))


def filter_str(param):
    raw = request.args.get(param)
    if raw is None or raw == "":
        return None
    return raw
