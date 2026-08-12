"""Request-shape validation (ladder rungs 19-22) and pagination (rung 21).

Fields are checked in three ordered passes so that the declared band order is
honoured even inside one endpoint:

  pass 1 - rung 19: every required field present and of the declared type
  pass 2 - rung 20: every enum-typed field carries a declared member
  pass 3 - rung 22: quantities that must be strictly positive
"""

from decimal import Decimal

from flask import request

from .constants import PAGINATION_DEFAULT_LIMIT, PAGINATION_MAX_LIMIT
from .errors import ApiError
from .util import dec, parse_instant

_MISSING = object()


def body_dict():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return payload


def field(name, kind, required=False, members=None, positive=False, default=None):
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "members": members,
        "positive": positive,
        "default": default,
    }


def _type_ok(kind, value):
    if kind == "string":
        return isinstance(value, str) and value.strip() != ""
    if kind == "enum":
        return isinstance(value, str) and value.strip() != ""
    if kind == "number":
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "datetime":
        return isinstance(value, str) and parse_instant(value) is not None
    if kind == "array":
        return isinstance(value, list)
    return True


def _coerce(kind, value):
    if kind == "number":
        return dec(value)
    if kind == "datetime":
        return parse_instant(value)
    if kind == "string" or kind == "enum":
        return value
    return value


def parse_body(payload, specs):
    """Validate and coerce a request body against an ordered spec list."""
    raw = {}
    result = {}

    # pass 1 -- presence and declared type
    for spec in specs:
        name = spec["name"]
        value = payload.get(name, _MISSING)
        if value is _MISSING or value is None:
            if spec["required"]:
                raise ApiError(
                    "ERR_VALIDATION", "Field '%s' is required." % name
                )
            raw[name] = _MISSING
            result[name] = spec["default"]
            continue
        if not _type_ok(spec["kind"], value):
            raise ApiError(
                "ERR_VALIDATION",
                "Field '%s' is not a valid %s." % (name, spec["kind"]),
            )
        raw[name] = value

    # pass 2 -- enum membership
    for spec in specs:
        name = spec["name"]
        if raw.get(name, _MISSING) is _MISSING:
            continue
        if spec["kind"] == "enum" and spec["members"] is not None:
            if raw[name] not in spec["members"]:
                raise ApiError(
                    "ERR_VALIDATION",
                    "Field '%s' must be one of %s."
                    % (name, ", ".join(spec["members"])),
                )

    # pass 3 -- strictly positive quantities
    for spec in specs:
        name = spec["name"]
        if raw.get(name, _MISSING) is _MISSING:
            continue
        if spec["positive"]:
            if dec(raw[name]) <= 0:
                raise ApiError(
                    "ERR_VALIDATION",
                    "Field '%s' must be strictly positive." % name,
                )

    for spec in specs:
        name = spec["name"]
        if raw.get(name, _MISSING) is not _MISSING:
            result[name] = _coerce(spec["kind"], raw[name])
    result["_supplied"] = set(k for k, v in raw.items() if v is not _MISSING)
    return result


def pagination():
    """Rung 21.  Returns (limit, offset)."""
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        text = args.get("limit")
        try:
            limit = int(str(text).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if str(text).strip() != str(limit):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(
                "ERR_VALIDATION",
                "limit must be between 1 and %d inclusive." % PAGINATION_MAX_LIMIT,
            )
    if "offset" in args:
        text = args.get("offset")
        try:
            offset = int(str(text).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if str(text).strip() != str(offset):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be at or above 0.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset: offset + limit], len(rows)


def query_enum(name, members):
    """A filter value drawn from a declared enumeration (rung 20)."""
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if members is not None and value not in members:
        raise ApiError(
            "ERR_VALIDATION",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(members)),
        )
    return value


def query_string(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    if name not in request.args:
        return None
    value = str(request.args.get(name)).strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be a boolean." % name)
