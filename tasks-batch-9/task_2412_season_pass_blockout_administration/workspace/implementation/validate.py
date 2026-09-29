"""Request schema validation (PRD 2.8 band 3 -> ERR_INVALID_REQUEST 400)."""

import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_day, parse_instant
from errors import ApiError
from response import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT, OFFSET_MIN

TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def field(kind, required=False, enum=None, minimum=None, maximum=None,
          exclusive_minimum=None, exclusive_maximum=None, max_decimals=None):
    return {
        "kind": kind,
        "required": required,
        "enum": enum,
        "minimum": minimum,
        "maximum": maximum,
        "exclusive_minimum": exclusive_minimum,
        "exclusive_maximum": exclusive_maximum,
        "max_decimals": max_decimals,
    }


def _check_bounds(name, value, spec):
    number = Decimal(str(value))
    if spec["minimum"] is not None and number < Decimal(str(spec["minimum"])):
        raise invalid("%s is below the permitted minimum" % name)
    if spec["maximum"] is not None and number > Decimal(str(spec["maximum"])):
        raise invalid("%s is above the permitted maximum" % name)
    if spec["exclusive_minimum"] is not None and number <= Decimal(str(spec["exclusive_minimum"])):
        raise invalid("%s is below the permitted minimum" % name)
    if spec["exclusive_maximum"] is not None and number >= Decimal(str(spec["exclusive_maximum"])):
        raise invalid("%s is above the permitted maximum" % name)


def _coerce(name, value, spec):
    kind = spec["kind"]
    if kind == "string":
        if not isinstance(value, str):
            raise invalid("%s must be a string" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            raise invalid("%s must be a string" % name)
        if value not in spec["enum"]:
            raise invalid("%s is not one of the permitted values" % name)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("%s must be an integer" % name)
        _check_bounds(name, value, spec)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid("%s must be a number" % name)
        if spec["max_decimals"] is not None:
            try:
                exponent = Decimal(str(value)).normalize().as_tuple().exponent
            except InvalidOperation:
                raise invalid("%s must be a number" % name)
            if isinstance(exponent, int) and exponent < -spec["max_decimals"]:
                raise invalid("%s has too many decimal places" % name)
        _check_bounds(name, value, spec)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise invalid("%s must be a boolean" % name)
        return value
    if kind == "date":
        if not isinstance(value, str):
            raise invalid("%s must be a date string" % name)
        try:
            parse_day(value)
        except Exception:
            raise invalid("%s must be an ISO 8601 date" % name)
        return value.strip()
    if kind == "datetime":
        if not isinstance(value, str):
            raise invalid("%s must be a timestamp string" % name)
        try:
            parse_instant(value)
        except Exception:
            raise invalid("%s must be an ISO 8601 timestamp" % name)
        return value.strip()
    if kind == "time":
        if not isinstance(value, str) or not TIME_RE.match(value.strip()):
            raise invalid("%s must be an HH:MM time" % name)
        return value.strip()
    if kind == "string_array":
        if not isinstance(value, list):
            raise invalid("%s must be an array" % name)
        for item in value:
            if not isinstance(item, str):
                raise invalid("%s must be an array of strings" % name)
        return list(value)
    raise invalid("%s is invalid" % name)


def read_body(spec):
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        payload = {}
    else:
        try:
            payload = json.loads(raw)
        except Exception:
            raise invalid("request body is not valid JSON")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise invalid("request body must be a JSON object")
    for key in payload:
        if key not in spec:
            raise invalid("unknown field %s" % key)
    result = {}
    for name, rule in spec.items():
        if name not in payload:
            if rule["required"]:
                raise invalid("%s is required" % name)
            continue
        value = payload[name]
        if value is None:
            if rule["required"]:
                raise invalid("%s is required" % name)
            continue
        result[name] = _coerce(name, value, rule)
    return result


# ---------- query parameters ----------

def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except Exception:
            raise invalid("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise invalid("limit is out of range")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except Exception:
            raise invalid("offset must be an integer")
        if offset < OFFSET_MIN:
            raise invalid("offset is out of range")
    return limit, offset


def query_enum(name, values):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        raise invalid("%s is not one of the permitted values" % name)
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except Exception:
        raise invalid("%s must be an integer" % name)
