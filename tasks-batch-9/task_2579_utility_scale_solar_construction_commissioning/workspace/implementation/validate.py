"""Auth (PRD 2.1), request-shape validation (ladder step 3) and query parsing."""

from flask import request

import clock
from errors import ApiError, fail, invalid

ROLES = (
    "EpcProjectManager",
    "CivilSuperintendent",
    "ProcurementCoordinator",
    "InstallationForeman",
    "UtilityCoordinator",
    "CommissioningEngineer",
    "OwnerEngineer",
    "LaborComplianceOfficer",
)

ALL_ROLES = ROLES


def actor():
    """Ladder step 1: both headers present and the role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(*allowed):
    """Ladder steps 1 then 2. Returns the acting X-User-ID."""
    user_id, role = actor()
    if allowed and role not in allowed:
        fail("ERR_FORBIDDEN_ROLE")
    return user_id


# --------------------------------------------------------------------------
# Body validation
# --------------------------------------------------------------------------

def _raw_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        invalid("Request body is not valid JSON")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        invalid("Request body must be a JSON object")
    return payload


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coerce(spec, value):
    name = spec["name"]
    kind = spec["type"]
    if kind == "string":
        if not isinstance(value, str):
            invalid("Field '%s' must be a string" % name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            invalid("Field '%s' must be a boolean" % name)
        return value
    if kind == "int":
        if not _is_int(value):
            invalid("Field '%s' must be an integer" % name)
        return _bounds(spec, value)
    if kind == "number":
        if not _is_num(value):
            invalid("Field '%s' must be a number" % name)
        return _bounds(spec, float(value))
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            invalid("Field '%s' must be one of %s" % (name, ", ".join(spec["values"])))
        return value
    if kind == "datetime":
        parsed = clock.parse_datetime(value)
        if parsed is None:
            invalid("Field '%s' must be an ISO 8601 instant" % name)
        return parsed
    if kind == "date":
        parsed = clock.parse_date(value)
        if parsed is None:
            invalid("Field '%s' must be a YYYY-MM-DD date" % name)
        return parsed
    return value


def _bounds(spec, value):
    name = spec["name"]
    if "gt" in spec and not value > spec["gt"]:
        invalid("Field '%s' must be greater than %s" % (name, spec["gt"]))
    if "ge" in spec and not value >= spec["ge"]:
        invalid("Field '%s' must be at least %s" % (name, spec["ge"]))
    if "lt" in spec and not value < spec["lt"]:
        invalid("Field '%s' must be less than %s" % (name, spec["lt"]))
    if "le" in spec and not value <= spec["le"]:
        invalid("Field '%s' must be at most %s" % (name, spec["le"]))
    return value


def body(*specs):
    """Validate the body against the declared field specs.

    Unknown fields, missing required fields, wrong types, enum values outside
    their declared set and numeric constraint violations are all
    ERR_INVALID_REQUEST (ladder step 3).
    """
    raw = _raw_body()
    allowed = set()
    for spec in specs:
        allowed.add(spec["name"])
    for key in raw:
        if key not in allowed:
            invalid("Unknown field '%s'" % key)
    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in raw or raw[name] is None:
            if spec.get("required"):
                invalid("Field '%s' is required" % name)
            out[name] = spec.get("default")
            continue
        out[name] = _coerce(spec, raw[name])
    return out


def s(name, required=True, **kw):
    return dict(name=name, type="string", required=required, **kw)


def i(name, required=True, **kw):
    return dict(name=name, type="int", required=required, **kw)


def n(name, required=True, **kw):
    return dict(name=name, type="number", required=required, **kw)


def b(name, required=True, **kw):
    return dict(name=name, type="bool", required=required, **kw)


def e(name, values, required=True, **kw):
    return dict(name=name, type="enum", values=tuple(values), required=required, **kw)


def dt(name, required=True, **kw):
    return dict(name=name, type="datetime", required=required, **kw)


def dy(name, required=True, **kw):
    return dict(name=name, type="date", required=required, **kw)


# --------------------------------------------------------------------------
# Query parameters (PRD 2.3)
# --------------------------------------------------------------------------

def page():
    """limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            invalid("limit must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            invalid("limit must be between 1 and 100")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            invalid("offset must be a non-negative integer")
        if offset < 0:
            invalid("offset must be at least 0")
    return limit, offset


def q(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qbool(name):
    value = q(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    invalid("Query parameter '%s' must be true or false" % name)


def window_bounds(start, end):
    """Ladder step 4: interval bounds strictly ordered."""
    if start is None or end is None:
        return
    if not start < end:
        fail("ERR_INVALID_WINDOW_BOUNDS")
