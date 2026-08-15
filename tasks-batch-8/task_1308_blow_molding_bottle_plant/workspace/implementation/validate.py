"""Request-shape validation (priority 3, ERR_INVALID_REQUEST) and query
pagination / filter parsing.

Field schema entry: (kind, required) or (kind, required, enum_set).
kinds: str, int, number, bool, datetime, enum, tiers, resin_list
All numeric fields must be non-negative (PRD 2.9 stage 3).
Explicit JSON null is treated as "absent".
"""
from decimal import Decimal

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST
from util import parse_iso

RESINS = {"PET", "HDPE", "PP"}


def get_body():
    """Return the JSON object body; {} when absent. Malformed JSON or a
    non-object body is a shape violation."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def _bad(msg):
    raise_err(ERR_INVALID_REQUEST, msg)


def _check_tiers(value):
    if not isinstance(value, list) or len(value) == 0:
        _bad("tiers must be a non-empty array")
    cleaned = []
    prev_min = None
    for tier in value:
        if not isinstance(tier, dict):
            _bad("each tier must be an object")
        extra = set(tier.keys()) - {"min_kg", "rate_cents_per_kg"}
        if extra:
            _bad("unknown tier field: %s" % sorted(extra)[0])
        if "min_kg" not in tier or tier["min_kg"] is None:
            _bad("tier min_kg is required")
        if "rate_cents_per_kg" not in tier or tier["rate_cents_per_kg"] is None:
            _bad("tier rate_cents_per_kg is required")
        min_kg = tier["min_kg"]
        rate = tier["rate_cents_per_kg"]
        if isinstance(min_kg, bool) or not isinstance(min_kg, (int, float)):
            _bad("tier min_kg must be a number")
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            _bad("tier rate_cents_per_kg must be a number")
        min_kg_d = Decimal(str(min_kg))
        rate_d = Decimal(str(rate))
        if min_kg_d < 0 or rate_d < 0:
            _bad("tier values must be non-negative")
        if prev_min is not None and min_kg_d <= prev_min:
            _bad("tiers must ascend in min_kg")
        prev_min = min_kg_d
        cleaned.append({"min_kg": min_kg_d, "rate_cents_per_kg": rate_d})
    if cleaned[0]["min_kg"] != 0:
        _bad("first tier min_kg must be 0")
    return cleaned


def check_fields(body, schema):
    """schema: {name: (kind, required[, enum_set])}.
    Enforces: required presence, no unknown fields, types, enum membership,
    numeric non-negativity. Returns cleaned values."""
    for key in body.keys():
        if key not in schema:
            _bad("unknown field: %s" % key)
    out = {}
    for name, spec in schema.items():
        kind = spec[0]
        required = spec[1]
        enum_set = spec[2] if len(spec) > 2 else None
        value = body.get(name, None)
        if value is None:
            if required:
                _bad("missing required field: %s" % name)
            continue
        if kind == "str":
            if not isinstance(value, str):
                _bad("field %s must be a string" % name)
            out[name] = value
        elif kind == "bool":
            if not isinstance(value, bool):
                _bad("field %s must be a boolean" % name)
            out[name] = value
        elif kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                _bad("field %s must be an integer" % name)
            if value < 0:
                _bad("field %s must be non-negative" % name)
            out[name] = value
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _bad("field %s must be a number" % name)
            d = Decimal(str(value))
            if d < 0:
                _bad("field %s must be non-negative" % name)
            out[name] = d
        elif kind == "datetime":
            dt = parse_iso(value)
            if dt is None:
                _bad("field %s must be an ISO 8601 datetime" % name)
            out[name] = dt
        elif kind == "enum":
            if not isinstance(value, str) or value not in enum_set:
                _bad("field %s must be one of %s" % (name, sorted(enum_set)))
            out[name] = value
        elif kind == "tiers":
            out[name] = _check_tiers(value)
        elif kind == "resin_list":
            if not isinstance(value, list):
                _bad("field %s must be an array" % name)
            for item in value:
                if not isinstance(item, str) or item not in RESINS:
                    _bad("field %s entries must be PET, HDPE or PP" % name)
            out[name] = list(value)
        else:  # pragma: no cover
            raise AssertionError("unknown kind " + kind)
    return out


def pagination_params():
    """limit: default 10, min 1, max 100 (clamped). offset: default 0,
    clamped >= 0. Non-integer values are a shape violation."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def query_filter(name, enum_set=None):
    """Read an optional query filter; when enum_set is given, an
    out-of-set value is a shape violation."""
    value = request.args.get(name)
    if value is None:
        return None
    if enum_set is not None and value not in enum_set:
        _bad("query parameter %s must be one of %s" % (name, sorted(enum_set)))
    return value


def query_number(name, required=False):
    raw = request.args.get(name)
    if raw is None:
        if required:
            _bad("missing required query parameter: %s" % name)
        return None
    try:
        d = Decimal(raw)
    except Exception:
        _bad("query parameter %s must be a number" % name)
    if d < 0:
        _bad("query parameter %s must be non-negative" % name)
    return d
