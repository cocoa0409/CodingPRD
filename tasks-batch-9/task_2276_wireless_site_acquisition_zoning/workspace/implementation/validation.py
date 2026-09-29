"""Request validation: auth (tier 1-2), body shape (tier 3), pagination (tier 4)."""

import json
from decimal import Decimal

from flask import request

from db import parse_iso
from errors import ApiError

ROLE_RF = "RfEngineer"
ROLE_AGENT = "SiteAcquisitionAgent"
ROLE_PLANNER = "ZoningPlanner"
ROLE_ENGINEER = "StructuralEngineer"
ROLE_ENVIRONMENTAL = "EnvironmentalReviewer"
ROLE_CONSTRUCTION = "ConstructionManager"
ROLE_DIRECTOR = "ProgramDirector"

ALL_ROLES = [
    ROLE_RF, ROLE_AGENT, ROLE_PLANNER, ROLE_ENGINEER,
    ROLE_ENVIRONMENTAL, ROLE_CONSTRUCTION, ROLE_DIRECTOR,
]

MISSING = object()

STRING = "string"
NUMBER = "number"
INTEGER = "integer"
BOOLEAN = "boolean"
DATETIME = "datetime"


class DtValue(object):
    """A validated datetime input: the raw client literal plus the parsed instant."""

    __slots__ = ("raw", "dt")

    def __init__(self, raw, dt):
        self.raw = raw
        self.dt = dt


def f(name, kind, required=True, enum=None, gt=None, ge=None, default=MISSING):
    return {
        "name": name, "kind": kind, "required": required, "enum": enum,
        "gt": gt, "ge": ge, "default": default,
    }


# ---------------------------------------------------------------------------
# tiers 1 & 2 -- authentication and authorization
# ---------------------------------------------------------------------------

def authenticate(roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403)
    return user_id, role


def actor_id():
    return request.headers.get("X-User-ID")


# ---------------------------------------------------------------------------
# tier 3 -- request body shape
# ---------------------------------------------------------------------------

def raw_body():
    data = request.get_data()
    if data is None or len(data.strip()) == 0:
        return {}
    try:
        parsed = json.loads(data.decode("utf-8"), parse_float=Decimal)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body is not valid JSON.")
    if parsed is None:
        return {}
    return parsed


def validate_body(specs):
    body = raw_body()
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")

    known = set(spec["name"] for spec in specs)
    for key in body.keys():
        if key not in known:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key)

    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in body:
            if spec["required"]:
                raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
            if spec["default"] is not MISSING:
                out[name] = spec["default"]
            continue
        out[name] = _coerce(name, body[name], spec)
    return out


def _bad(name, detail):
    raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s %s" % (name, detail))


def _coerce(name, value, spec):
    kind = spec["kind"]
    if kind == STRING:
        if not isinstance(value, str):
            _bad(name, "must be a string.")
        if spec["enum"] is not None and value not in spec["enum"]:
            _bad(name, "must be one of: %s" % ", ".join(spec["enum"]))
        return value
    if kind == BOOLEAN:
        if not isinstance(value, bool):
            _bad(name, "must be a boolean.")
        return value
    if kind == INTEGER:
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer.")
        _check_bounds(name, Decimal(value), spec)
        return value
    if kind == NUMBER:
        if isinstance(value, bool):
            _bad(name, "must be a number.")
        if isinstance(value, int):
            value = Decimal(value)
        elif not isinstance(value, Decimal):
            _bad(name, "must be a number.")
        _check_bounds(name, value, spec)
        return value
    if kind == DATETIME:
        if not isinstance(value, str):
            _bad(name, "must be an ISO 8601 date-time string.")
        try:
            parsed = parse_iso(value)
        except Exception:
            _bad(name, "must be an ISO 8601 date-time string.")
        return DtValue(value, parsed)
    raise AssertionError("unknown kind " + kind)


def _check_bounds(name, value, spec):
    if spec["gt"] is not None and not value > Decimal(str(spec["gt"])):
        _bad(name, "must be greater than %s." % spec["gt"])
    if spec["ge"] is not None and not value >= Decimal(str(spec["ge"])):
        _bad(name, "must be greater than or equal to %s." % spec["ge"])


def require_conditional(values, name):
    if values.get(name) is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field %s is required for this action." % name)
    return values[name]


# ---------------------------------------------------------------------------
# tier 4 -- pagination
# ---------------------------------------------------------------------------

def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", 400)
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", 400)
    return limit, offset
