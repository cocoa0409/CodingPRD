"""Request shape validation — ladder rung 4 (ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError

MAX_LIMIT = 100
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------- field specs

def field(name, kind, required=False, default=None, **constraints):
    spec = {"name": name, "kind": kind, "required": required, "default": default}
    spec.update(constraints)
    return spec


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coerce(spec, value):
    name = spec["name"]
    kind = spec["kind"]

    if kind in ("string", "id"):
        if not isinstance(value, str):
            raise invalid("Field '%s' must be a string" % name)
        if not spec.get("allow_blank") and value.strip() == "":
            raise invalid("Field '%s' must not be empty" % name)
        max_length = spec.get("max_length")
        if max_length is not None and len(value) > max_length:
            raise invalid("Field '%s' must be at most %d characters" % (name, max_length))
        return value

    if kind == "enum":
        if not isinstance(value, str):
            raise invalid("Field '%s' must be a string" % name)
        if value not in spec["values"]:
            raise invalid("Field '%s' must be one of %s" % (name, ", ".join(spec["values"])))
        return value

    if kind == "integer":
        if not _is_int(value):
            raise invalid("Field '%s' must be an integer" % name)
        return _range_check(spec, Decimal(value), value)

    if kind == "number":
        if not _is_number(value):
            raise invalid("Field '%s' must be a number" % name)
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            raise invalid("Field '%s' must be a number" % name)
        max_decimals = spec.get("max_decimals")
        if max_decimals is not None:
            exponent = dec.as_tuple().exponent
            if not isinstance(exponent, int) or -exponent > max_decimals:
                raise invalid("Field '%s' allows at most %d decimal places"
                              % (name, max_decimals))
        _range_check(spec, dec, value)
        return dec

    if kind == "boolean":
        if not isinstance(value, bool):
            raise invalid("Field '%s' must be a boolean" % name)
        return value

    if kind == "datetime":
        if not isinstance(value, str):
            raise invalid("Field '%s' must be an ISO 8601 timestamp string" % name)
        try:
            clock.parse(value)
        except (ValueError, TypeError):
            raise invalid("Field '%s' must be a valid ISO 8601 timestamp" % name)
        return value

    if kind == "object":
        if not isinstance(value, dict):
            raise invalid("Field '%s' must be an object" % name)
        return value

    if kind == "string_array":
        if not isinstance(value, list):
            raise invalid("Field '%s' must be an array" % name)
        min_items = spec.get("min_items")
        max_items = spec.get("max_items")
        if min_items is not None and len(value) < min_items:
            raise invalid("Field '%s' requires at least %d entries" % (name, min_items))
        if max_items is not None and len(value) > max_items:
            raise invalid("Field '%s' allows at most %d entries" % (name, max_items))
        for item in value:
            if not isinstance(item, str) or item.strip() == "":
                raise invalid("Field '%s' must contain non-empty strings" % name)
        if spec.get("unique_items") and len(set(value)) != len(value):
            raise invalid("Field '%s' must not contain duplicates" % name)
        return list(value)

    raise invalid("Field '%s' is not understood" % name)


def _range_check(spec, dec, original):
    name = spec["name"]
    minimum = spec.get("minimum")
    maximum = spec.get("maximum")
    exclusive_max = spec.get("exclusive_maximum")
    if minimum is not None and dec < Decimal(str(minimum)):
        raise invalid("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise invalid("Field '%s' must be <= %s" % (name, maximum))
    if exclusive_max is not None and dec >= Decimal(str(exclusive_max)):
        raise invalid("Field '%s' must be < %s" % (name, exclusive_max))
    return original


def read_body():
    if request.data and request.data.strip():
        try:
            payload = request.get_json(force=True, silent=False)
        except Exception:
            raise invalid("Request body must be valid JSON")
    else:
        payload = None
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object")
    return payload


def parse_body(specs):
    """Validate the JSON body against `specs`; returns (values, present_keys)."""
    payload = read_body()
    allowed = {spec["name"] for spec in specs}
    for key in payload:
        if key not in allowed:
            raise invalid("Unknown field '%s'" % key)
    values = {}
    present = set()
    for spec in specs:
        name = spec["name"]
        if name not in payload or payload[name] is None:
            if name in payload and payload[name] is None and spec.get("required"):
                raise invalid("Field '%s' is required" % name)
            if spec.get("required"):
                raise invalid("Field '%s' is required" % name)
            if name in payload:
                present.add(name)
            values[name] = spec.get("default")
            continue
        present.add(name)
        values[name] = _coerce(spec, payload[name])
    return values, present


# ---------------------------------------------------------------- query specs

def parse_query(specs):
    """Validate query params; always accepts limit/offset."""
    allowed = {spec["name"] for spec in specs} | {"limit", "offset"}
    for key in request.args:
        if key not in allowed:
            raise invalid("Unknown query parameter '%s'" % key)

    values = {}
    for spec in specs:
        name = spec["name"]
        if name not in request.args:
            values[name] = None
            continue
        raw = request.args.get(name)
        kind = spec["kind"]
        if kind == "enum":
            if raw not in spec["values"]:
                raise invalid("Query parameter '%s' must be one of %s"
                              % (name, ", ".join(spec["values"])))
            values[name] = raw
        elif kind == "boolean":
            low = raw.strip().lower()
            if low not in ("true", "false"):
                raise invalid("Query parameter '%s' must be true or false" % name)
            values[name] = (low == "true")
        elif kind == "integer":
            values[name] = _query_int(name, raw)
        else:
            if raw.strip() == "":
                raise invalid("Query parameter '%s' must not be empty" % name)
            values[name] = raw

    values["limit"] = _limit()
    values["offset"] = _offset()
    return values


def _query_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer" % name)


def _limit():
    raw = request.args.get("limit")
    if raw is None:
        return DEFAULT_LIMIT
    value = _query_int("limit", raw)
    if value < 1 or value > MAX_LIMIT:
        raise invalid("Query parameter 'limit' must be between 1 and %d" % MAX_LIMIT)
    return value


def _offset():
    raw = request.args.get("offset")
    if raw is None:
        return DEFAULT_OFFSET
    value = _query_int("offset", raw)
    if value < 0:
        raise invalid("Query parameter 'offset' must be >= 0")
    return value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
