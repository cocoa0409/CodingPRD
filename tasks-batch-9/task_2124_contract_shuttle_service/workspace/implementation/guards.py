"""Request screening ladder helpers (PRD section 2.6).

Rung 1  header presence          -> ERR_UNAUTHENTICATED (401)
Rung 2  role recognition         -> ERR_UNAUTHENTICATED (401)
Rung 3  role authorisation       -> ERR_FORBIDDEN_ROLE  (403)
Rung 4  driver ownership         -> ERR_DRIVER_NOT_ASSIGNED (403)
Rung 5  request shape            -> ERR_INVALID_REQUEST (400)
Rung 6  pagination shape         -> ERR_INVALID_PAGINATION (400)   [envelope.py]
Rung 7  path existence           -> 404
Rung 8  body reference existence -> 404
"""

import datetime as _dt
import re

from flask import request

from errors import ApiError

ROLES = ("ContractAdmin", "ClientLiaison", "OpsPlanner", "FleetManager", "DriverUser")
ALL_ROLES = list(ROLES)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authorize(allowed_roles):
    """Rungs 1-3."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return Caller(user_id, role)


def body():
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        return {}
    return data


# ------------------------------------------------------------------ existence
def must_exist(table, key, error_id):
    """Rung 7 / rung 8."""
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = table.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


# ------------------------------------------------------------- shape checking
def _bad(field, why):
    return ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        return None


def validate_body(raw, spec):
    """Rung 5.  `spec` is a list of field descriptors."""
    out = {}
    for field in spec:
        name = field["name"]
        required = field.get("required", True)
        if name not in raw:
            if required:
                raise _bad(name, "is required")
            out[name] = field.get("default")
            continue
        value = raw[name]
        if value is None:
            if field.get("nullable"):
                out[name] = None
                continue
            raise _bad(name, "may not be null")
        kind = field["kind"]
        if kind == "string":
            if not isinstance(value, str):
                raise _bad(name, "must be a string")
            min_len = field.get("min_len", 1)
            max_len = field.get("max_len")
            if len(value) < min_len:
                raise _bad(name, "is shorter than %d characters" % min_len)
            if max_len is not None and len(value) > max_len:
                raise _bad(name, "is longer than %d characters" % max_len)
        elif kind == "int":
            if not is_int(value):
                raise _bad(name, "must be an integer")
            if "min" in field and value < field["min"]:
                raise _bad(name, "is below its minimum of %s" % field["min"])
            if "max" in field and value > field["max"]:
                raise _bad(name, "is above its maximum of %s" % field["max"])
        elif kind == "number":
            if not is_number(value):
                raise _bad(name, "must be a number")
            if "min" in field and value < field["min"]:
                raise _bad(name, "is below its minimum of %s" % field["min"])
            if "max" in field and value > field["max"]:
                raise _bad(name, "is above its maximum of %s" % field["max"])
        elif kind == "bool":
            if not isinstance(value, bool):
                raise _bad(name, "must be a boolean")
        elif kind == "enum":
            if not isinstance(value, str) or value not in field["values"]:
                raise _bad(name, "must be one of %s" % ", ".join(field["values"]))
        elif kind == "date":
            if parse_date(value) is None:
                raise _bad(name, "must be a YYYY-MM-DD calendar date")
        else:  # pragma: no cover - programming error
            raise _bad(name, "has an unknown declared type")
        out[name] = value
    return out


def minute_field(name, required=True, nullable=False):
    return {"name": name, "kind": "int", "min": 0, "max": 1439,
            "required": required, "nullable": nullable}


def id_field(name, required=True, nullable=False):
    return {"name": name, "kind": "string", "min_len": 1, "required": required,
            "nullable": nullable}


# --------------------------------------------------------- collection filters
def equality_filter(rows, param, key, coerce=None):
    raw = request.args.get(param)
    if raw is None:
        return rows
    if coerce is not None:
        wanted = coerce(raw)
        return [r for r in rows if r.get(key) == wanted]
    return [r for r in rows if r.get(key) == raw]


def bool_param(raw):
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None
