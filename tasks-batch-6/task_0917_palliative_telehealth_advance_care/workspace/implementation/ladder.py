"""The 31-rung rejection ladder (PRD 2.5), expressed as ordered primitives.

Every route calls these helpers strictly in ascending rung order:

  1  auth()            2  auth()            3  path_row()
  4  validate()        5  fk()              6  freeze_gate()
  7  state()           8  occ()             9+ endpoint-specific rungs

ENUM ROUTING (adjudicated once, here): PRD rung 4 says an enum-membership
failure "is reported with this same error identifier; there is no separate enum
error code".  Every enum check on every request body field therefore routes
through :func:`_check_enum` to ERR_VALIDATION.  List filter query parameters are
*not* validated at all (PRD 2.3 declares only ``limit``/``offset`` bounds a
request-shape failure), so an off-enum filter simply matches no row and returns
an empty page.
"""

from datetime import datetime
from decimal import Decimal

from flask import g, request

import config
from errors import (
    ERR_RECORD_FROZEN, ERR_RESOURCE_NOT_FOUND, ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED, ERR_VALIDATION, api_error,
)
from store import DATE_RE, parse_iso, store


# ------------------------------------------------------------------ rungs 1-2
class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in config.ALL_ROLES:
        raise api_error(ERR_UNAUTHENTICATED)
    if role not in allowed_roles:
        raise api_error(ERR_UNAUTHORIZED)
    return Ctx(user_id, role)


# -------------------------------------------------------------------- rung 3
def path_row(table, row_id):
    row = table.get(row_id)
    if row is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return row


# -------------------------------------------------------------------- rung 4
def raw_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True, force=True)
    if body is None:
        raise api_error(ERR_VALIDATION, "Request body is not valid JSON.")
    if not isinstance(body, dict):
        raise api_error(ERR_VALIDATION, "Request body must be a JSON object.")
    return body


def field(name, kind, required=False, enum=None, lo=None, hi=None,
          default=None, item_kind=None, item_enum=None, gt=None, nonempty=False):
    return {
        "name": name, "kind": kind, "required": required, "enum": enum,
        "lo": lo, "hi": hi, "default": default, "item_kind": item_kind,
        "item_enum": item_enum, "gt": gt, "nonempty": nonempty,
    }


def _bad(name, why):
    raise api_error(ERR_VALIDATION, "%s %s." % (name, why))


def _check_enum(name, value, members):
    if value not in members:
        _bad(name, "must be one of %s" % ", ".join(members))


def _coerce(spec, value):
    name, kind = spec["name"], spec["kind"]
    if kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if spec["nonempty"] and not value.strip():
            _bad(name, "must be non-empty")
        return value
    if kind == "date":
        if not isinstance(value, str) or not DATE_RE.match(value):
            _bad(name, "must be a YYYY-MM-DD date string")
        return value
    if kind == "enum":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        _check_enum(name, value, spec["enum"])
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(name, "must be an integer")
        if spec["lo"] is not None and value < spec["lo"]:
            _bad(name, "must be at least %s" % spec["lo"])
        if spec["hi"] is not None and value > spec["hi"]:
            _bad(name, "must be at most %s" % spec["hi"])
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(name, "must be a number")
        dec = Decimal(str(value))
        if spec["gt"] is not None and dec <= Decimal(str(spec["gt"])):
            _bad(name, "must be greater than %s" % spec["gt"])
        if spec["lo"] is not None and dec < Decimal(str(spec["lo"])):
            _bad(name, "must be at least %s" % spec["lo"])
        if spec["hi"] is not None and dec > Decimal(str(spec["hi"])):
            _bad(name, "must be at most %s" % spec["hi"])
        return dec
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "datetime":
        dt = parse_iso(value) if isinstance(value, str) else None
        if dt is None:
            _bad(name, "must be a valid ISO 8601 instant")
        return dt
    if kind == "array":
        if not isinstance(value, list):
            _bad(name, "must be an array")
        out = []
        for item in value:
            if spec["item_kind"] == "string":
                if not isinstance(item, str):
                    _bad(name, "must contain only strings")
            elif spec["item_kind"] == "enum":
                if not isinstance(item, str):
                    _bad(name, "must contain only strings")
                _check_enum(name, item, spec["item_enum"])
            out.append(item)
        return out
    raise RuntimeError("unknown kind %s" % kind)


def validate(body, specs):
    """Rung 4 — request shape: presence, declared type, enum membership, bounds."""
    out = {}
    for spec in specs:
        name = spec["name"]
        present = name in body and body[name] is not None
        if not present:
            if spec["required"]:
                _bad(name, "is required")
            out[name] = spec["default"]
            continue
        out[name] = _coerce(spec, body[name])
    return out


def require_order(start, end, start_name, end_name):
    """Rung 4 — datetime pair ordering: end must be strictly after start."""
    if start is not None and end is not None and not (end > start):
        _bad(end_name, "must be strictly after %s" % start_name)


# -------------------------------------------------------------------- rung 5
def fk(table, row_id):
    if row_id is None:
        return None
    row = table.get(row_id)
    if row is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return row


# -------------------------------------------------------------------- rung 6
def freeze_gate(patient):
    if patient is not None and patient.get("records_frozen"):
        raise api_error(ERR_RECORD_FROZEN)


# -------------------------------------------------------------------- rung 7
def state(condition, message=None):
    if not condition:
        from errors import ERR_INVALID_STATE
        raise api_error(ERR_INVALID_STATE, message)


# -------------------------------------------------------------------- rung 8
def occ(supplied, current, error_id):
    if supplied != current:
        raise api_error(error_id)


# ------------------------------------------------------------- row mutation
def touch(row):
    """Refresh updated_at and bump version — at most once per row per request."""
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = id(row)
    if key in touched:
        row["updated_at"] = store.now()
        return row
    touched.add(key)
    row["updated_at"] = store.now()
    row["version"] = row.get("version", 1) + 1
    return row


# ---------------------------------------------------------------- pagination
def _page_int(name, raw, default, lo, hi):
    if raw is None or raw == "":
        if raw == "":
            _bad(name, "must be an integer")
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _bad(name, "must be an integer")
    if lo is not None and value < lo:
        _bad(name, "must be at least %s" % lo)
    if hi is not None and value > hi:
        _bad(name, "must be at most %s" % hi)
    return value


def pagination():
    limit = _page_int("limit", request.args.get("limit"),
                      config.PAGE_LIMIT_DEFAULT, config.PAGE_LIMIT_MIN,
                      config.PAGE_LIMIT_MAX)
    offset = _page_int("offset", request.args.get("offset"),
                       config.PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def apply_filters(rows, filters):
    """Domain filters combine conjunctively; an unmatched value yields no rows."""
    out = []
    for row in rows:
        keep = True
        for key, wanted in filters.items():
            if wanted is None:
                continue
            if row.get(key) != wanted:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def query_filters(names):
    return {name: request.args.get(name) for name in names}


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def isodt(value):
    return value if isinstance(value, datetime) else parse_iso(value)
