"""Request-shape validation (PRD 2.5 step 6) and pagination bounds (PRD 2.3)."""

import re

from flask import request

from errors import ApiError
from store import S, parse_iso

_UPPER_ALNUM = re.compile(r"^[A-Z0-9]+$")
_UPPER_ALPHA = re.compile(r"^[A-Z]+$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.?[^@\s]*$")

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def field(name, kind, required=True, **kw):
    spec = {"name": name, "kind": kind, "required": required}
    spec.update(kw)
    return spec


def json_body():
    """Parse the request body; anything that is not a JSON object is malformed."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def raw_str(body, name):
    """Fetch a body value only when it is usable as a foreign key lookup."""
    value = body.get(name)
    return value if isinstance(value, str) else None


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def _check_int(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % name)
    if spec.get("cents") and value < 0:
        _bad("%s must be a non-negative integer number of cents." % name)
    if "min" in spec and value < spec["min"]:
        _bad("%s must be at least %s." % (name, spec["min"]))
    if "max" in spec and value > spec["max"]:
        _bad("%s must be at most %s." % (name, spec["max"]))


def _check_number(name, value, spec):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("%s must be a number." % name)
    if "min" in spec and value < spec["min"]:
        _bad("%s must be at least %s." % (name, spec["min"]))
    if "max" in spec and value > spec["max"]:
        _bad("%s must be at most %s." % (name, spec["max"]))


def _check_string(name, value, spec):
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if "exact_len" in spec and len(value) != spec["exact_len"]:
        _bad("%s must be exactly %d characters." % (name, spec["exact_len"]))
    if "min_len" in spec and len(value) < spec["min_len"]:
        _bad("%s must be at least %d characters." % (name, spec["min_len"]))
    if "max_len" in spec and len(value) > spec["max_len"]:
        _bad("%s must be at most %d characters." % (name, spec["max_len"]))
    pattern = spec.get("pattern")
    if pattern == "upper_alnum" and not _UPPER_ALNUM.match(value):
        _bad("%s must be uppercase alphanumeric." % name)
    if pattern == "upper_alpha" and not _UPPER_ALPHA.match(value):
        _bad("%s must be uppercase letters." % name)
    if pattern == "email" and ("@" not in value or not _EMAIL.match(value)):
        _bad("%s must be a syntactically valid email address." % name)


def validate(body, specs):
    """Validate the body against an ordered field spec and return parsed values."""
    names = set(spec["name"] for spec in specs)

    for spec in specs:
        if spec["required"] and body.get(spec["name"]) is None:
            _bad("%s is required." % spec["name"])

    for key in body.keys():
        if key not in names:
            _bad("Unknown field %s." % key)

    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in body or body[name] is None:
            continue
        value = body[name]
        kind = spec["kind"]
        if kind == "int":
            _check_int(name, value, spec)
            out[name] = value
        elif kind == "number":
            _check_number(name, value, spec)
            out[name] = value
        elif kind == "bool":
            if not isinstance(value, bool):
                _bad("%s must be a boolean." % name)
            out[name] = value
        elif kind == "enum":
            if not isinstance(value, str):
                _bad("%s must be a string." % name)
            if value not in spec["values"]:
                _bad("%s must be one of %s." % (name, ", ".join(spec["values"])))
            out[name] = value
        elif kind == "datetime":
            if not isinstance(value, str):
                _bad("%s must be an ISO 8601 UTC timestamp string." % name)
            try:
                out[name] = parse_iso(value)
            except (ValueError, TypeError):
                _bad("%s must be an ISO 8601 UTC timestamp." % name)
        else:
            _check_string(name, value, spec)
            out[name] = value
    return out


# --------------------------------------------------------------------------
# pagination + filters
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw).strip() != str(limit):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw).strip() != str(offset):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit]


def filter_eq(rows, param, attr=None):
    """Narrow rows by an exact-match query parameter when it is supplied."""
    value = request.args.get(param)
    if value is None:
        return rows
    key = attr or param
    return [row for row in rows if row.get(key) == value]


# --------------------------------------------------------------------------
# existence helpers (PRD 2.5 steps 4 and 5)
# --------------------------------------------------------------------------

_LOOKUP = {
    "policy_profile": ("policy_profiles", "ERR_POLICY_PROFILE_NOT_FOUND"),
    "passenger": ("passengers", "ERR_PASSENGER_NOT_FOUND"),
    "booking": ("bookings", "ERR_BOOKING_NOT_FOUND"),
    "flight_segment": ("flight_segments", "ERR_FLIGHT_SEGMENT_NOT_FOUND"),
    "ancillary_purchase": ("ancillary_purchases", "ERR_ANCILLARY_PURCHASE_NOT_FOUND"),
    "checked_bag": ("checked_bags", "ERR_CHECKED_BAG_NOT_FOUND"),
    "denied_boarding_record": ("denied_boarding_records", "ERR_DENIED_BOARDING_RECORD_NOT_FOUND"),
    "tarmac_delay_event": ("tarmac_delay_events", "ERR_TARMAC_DELAY_EVENT_NOT_FOUND"),
    "refund_obligation": ("refund_obligations", "ERR_REFUND_OBLIGATION_NOT_FOUND"),
    "consumer_complaint": ("consumer_complaints", "ERR_CONSUMER_COMPLAINT_NOT_FOUND"),
    "regulator_report": ("regulator_reports", "ERR_REGULATOR_REPORT_NOT_FOUND"),
}


def must_exist(kind, row_id):
    collection, error_id = _LOOKUP[kind]
    row = getattr(S, collection).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def body_fk(body, name, kind):
    """Resolve a body foreign key; absent or non-string values fall through to shape checks."""
    value = raw_str(body, name)
    if value is None:
        return None
    return must_exist(kind, value)
