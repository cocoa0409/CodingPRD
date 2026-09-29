"""Priority-3 schema validation (PRD §2.11 step 3) and pagination parsing.

Fields are walked in the order the owning entity declares them, and the
passes run: missing/null required -> wrong type -> bad enum -> out of range /
bad string / bad format, then unknown body fields.  Every failure in this
band reports ERR_INVALID_REQUEST.
"""

import json
import re
from decimal import Decimal

from flask import request

from db import parse_date, parse_datetime
from errors import ApiError, bad_request


def field(name, ftype, required=False, enum=None, gt=None, ge=None, lt=None, le=None,
          minlen=None, maxlen=None, pattern=None, nullable=False, max_dp=None):
    return {
        "name": name, "type": ftype, "required": required, "enum": enum,
        "gt": gt, "ge": ge, "lt": lt, "le": le, "minlen": minlen, "maxlen": maxlen,
        "pattern": pattern, "nullable": nullable, "max_dp": max_dp,
    }


def read_body():
    """Parse the JSON body; a missing body is treated as an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        raise bad_request("Malformed JSON body.")
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object.")
    return parsed


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return (isinstance(value, (int, float, Decimal)) and not isinstance(value, bool))


def _type_ok(value, ftype):
    if ftype == "string":
        return isinstance(value, str)
    if ftype == "int":
        return _is_int(value)
    if ftype == "number":
        return _is_number(value)
    if ftype == "bool":
        return isinstance(value, bool)
    if ftype in ("date", "datetime"):
        return isinstance(value, str)
    if ftype == "array":
        return isinstance(value, list)
    if ftype == "object":
        return isinstance(value, dict)
    return True


def _range_ok(spec, value):
    ftype = spec["type"]
    if ftype in ("int", "number"):
        num = Decimal(value) if not isinstance(value, Decimal) else value
        if spec["gt"] is not None and not num > Decimal(str(spec["gt"])):
            return False
        if spec["ge"] is not None and not num >= Decimal(str(spec["ge"])):
            return False
        if spec["lt"] is not None and not num < Decimal(str(spec["lt"])):
            return False
        if spec["le"] is not None and not num <= Decimal(str(spec["le"])):
            return False
        if spec["max_dp"] is not None:
            exponent = num.as_tuple().exponent
            if isinstance(exponent, int) and -exponent > spec["max_dp"]:
                return False
        return True
    if ftype == "string":
        if spec["minlen"] is not None:
            if len(value.strip()) < spec["minlen"]:
                return False
        if spec["maxlen"] is not None and len(value) > spec["maxlen"]:
            return False
        if spec["pattern"] is not None and not re.match(spec["pattern"], value):
            return False
        return True
    if ftype == "date":
        return parse_date(value) is not None
    if ftype == "datetime":
        return parse_datetime(value) is not None
    return True


def validate(body, specs):
    """Validate a request body against an ordered field spec list."""
    if not isinstance(body, dict):
        raise bad_request()
    allowed = {spec["name"] for spec in specs}

    for spec in specs:
        if spec["required"] and (spec["name"] not in body or body[spec["name"]] is None):
            raise bad_request("Missing required field: %s" % spec["name"])
    for spec in specs:
        if spec["name"] not in body:
            continue
        value = body[spec["name"]]
        if value is None:
            if spec["nullable"] or not spec["required"]:
                if not spec["nullable"]:
                    raise bad_request("Field %s may not be null." % spec["name"])
                continue
        if not _type_ok(value, spec["type"]):
            raise bad_request("Field %s has the wrong type." % spec["name"])
    for spec in specs:
        value = body.get(spec["name"])
        if value is None or spec["enum"] is None:
            continue
        if value not in spec["enum"]:
            raise bad_request("Field %s carries an invalid value." % spec["name"])
    for spec in specs:
        value = body.get(spec["name"])
        if value is None:
            continue
        if not _range_ok(spec, value):
            raise bad_request("Field %s is out of range." % spec["name"])

    for key in body:
        if key not in allowed:
            raise bad_request("Unknown field: %s" % key)
    return body


def pagination():
    """limit / offset from the query string (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        if not re.match(r"^-?\d+$", limit_raw.strip()):
            raise bad_request("limit must be an integer.")
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            raise bad_request("limit must be between 1 and 100.")
    if offset_raw is not None:
        if not re.match(r"^-?\d+$", offset_raw.strip()):
            raise bad_request("offset must be an integer.")
        offset = int(offset_raw)
        if offset < 0:
            raise bad_request("offset may not be negative.")
    return limit, offset


def enum_filter(name, allowed):
    """Read an enumerated query filter; an out-of-set value is invalid."""
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad_request("Filter %s carries an invalid value." % name)
    return value


def str_filter(name):
    return request.args.get(name)
