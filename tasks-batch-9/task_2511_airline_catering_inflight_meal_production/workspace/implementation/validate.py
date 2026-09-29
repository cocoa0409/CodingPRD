"""Request shape validation (PRD 2.6 priority 30) and pagination (PRD 2.3).

Unknown fields are rejected rather than ignored; every declared field must
match its JSON type, every enum value must be a declared member and every
bounded number must sit inside its range.  All failures raise
ERR_INVALID_REQUEST (400).
"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from timeutil import parse_date, parse_instant

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

_INT_RE = re.compile(r"^[+-]?\d+$")


def _bad(msg):
    fail("ERR_INVALID_REQUEST", msg)


def raw_body():
    """Return the JSON body as a dict.  An absent body counts as {}."""
    data = request.get_data(cache=True)
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        _bad("Request body is not valid JSON.")
        return {}
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


def _check_value(name, value, spec):
    kind = spec.get("type")
    if value is None:
        if spec.get("nullable"):
            return None
        _bad("Field '%s' may not be null." % name)

    if kind == "string":
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        if spec.get("non_empty") and value.strip() == "":
            _bad("Field '%s' may not be empty." % name)
        pattern = spec.get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            _bad("Field '%s' is malformed." % name)
        return value

    if kind == "enum":
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        if value not in spec["values"]:
            _bad("Field '%s' is not a declared member." % name)
        return value

    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad("Field '%s' must be an integer." % name)
        if spec.get("min") is not None and value < spec["min"]:
            _bad("Field '%s' is below its minimum." % name)
        if spec.get("max") is not None and value > spec["max"]:
            _bad("Field '%s' is above its maximum." % name)
        return value

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad("Field '%s' must be a number." % name)
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            _bad("Field '%s' must be a number." % name)
            return None
        places = spec.get("decimals")
        if places is not None and -dec.as_tuple().exponent > places:
            _bad("Field '%s' carries too many decimal places." % name)
        if spec.get("min") is not None and dec < Decimal(str(spec["min"])):
            _bad("Field '%s' is below its minimum." % name)
        if spec.get("max") is not None and dec > Decimal(str(spec["max"])):
            _bad("Field '%s' is above its maximum." % name)
        return dec

    if kind == "bool":
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean." % name)
        return value

    if kind == "datetime":
        parsed = parse_instant(value)
        if parsed is None:
            _bad("Field '%s' is not an ISO 8601 UTC instant." % name)
        return parsed

    if kind == "date":
        parsed = parse_date(value)
        if parsed is None:
            _bad("Field '%s' is not a YYYY-MM-DD date." % name)
        return value

    if kind == "id":
        if not isinstance(value, str) or value.strip() == "":
            _bad("Field '%s' must be an identifier string." % name)
        return value

    if kind == "array":
        if not isinstance(value, list):
            _bad("Field '%s' must be an array." % name)
        if spec.get("min_items") is not None and len(value) < spec["min_items"]:
            _bad("Field '%s' has too few entries." % name)
        item_spec = spec.get("item")
        out = []
        for idx, item in enumerate(value):
            out.append(_check_value("%s[%d]" % (name, idx), item, item_spec))
        if spec.get("unique") and len(set(value)) != len(value):
            _bad("Field '%s' contains duplicates." % name)
        return out

    if kind == "object":
        if not isinstance(value, dict):
            _bad("Field '%s' must be an object." % name)
        return check_fields(value, spec["fields"], prefix=name + ".")

    _bad("Field '%s' is not understood." % name)
    return None


def check_fields(payload, fields, prefix=""):
    """Validate a mapping against a field spec list of (name, spec) pairs."""
    declared = {name for name, _ in fields}
    for key in payload.keys():
        if key not in declared:
            _bad("Unknown field '%s%s'." % (prefix, key))
    out = {}
    for name, spec in fields:
        if name in payload:
            out[name] = _check_value(prefix + name, payload[name], spec)
        elif spec.get("required"):
            _bad("Field '%s%s' is required." % (prefix, name))
        elif "default" in spec:
            out[name] = spec["default"]
    return out


def body(fields):
    return check_fields(raw_body(), fields)


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    if not _INT_RE.match(raw.strip()):
        _bad("Query parameter '%s' must be an integer." % name)
    value = int(raw.strip())
    if value < minimum:
        _bad("Query parameter '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        _bad("Query parameter '%s' is above its maximum." % name)
    return value


def pagination(extra_params=None):
    """Validate the query string and return (filters, limit, offset)."""
    allowed = dict(extra_params or {})
    known = set(allowed) | {"limit", "offset"}
    for key in request.args.keys():
        if key not in known:
            _bad("Unknown query parameter '%s'." % key)

    limit = _query_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _query_int("offset", PAGE_OFFSET_DEFAULT, 0, None)

    filters = {}
    for key, spec in allowed.items():
        raw = request.args.get(key)
        if raw is None:
            continue
        kind = spec.get("type")
        if kind == "enum":
            if raw not in spec["values"]:
                _bad("Query parameter '%s' is not a declared member." % key)
            filters[key] = raw
        elif kind == "int":
            filters[key] = _query_int(key, None, spec.get("min", -10 ** 12), spec.get("max"))
        elif kind == "bool":
            if raw.lower() not in ("true", "false"):
                _bad("Query parameter '%s' must be a boolean." % key)
            filters[key] = raw.lower() == "true"
        else:
            filters[key] = raw
    return filters, limit, offset


def page(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
