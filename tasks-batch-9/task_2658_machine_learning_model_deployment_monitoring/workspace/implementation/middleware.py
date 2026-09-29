"""Auth extraction, RBAC, body/query validation helpers.

Header names, role names, pagination parameter names and error ids all come
straight from PRD 2.1 / 2.2 / 2.3.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

MLE = "MLEngineer"
DS = "DataSteward"
MA = "ModelApprover"
RE = "ReliabilityEngineer"
PA = "PlatformAdmin"

ROLES = (MLE, DS, MA, RE, PA)
ALL_ROLES = ROLES


def auth(*allowed):
    """PRD 2.7 band 1: ERR_UNAUTHENTICATED then ERR_ROLE_NOT_PERMITTED, both
    before any path resolution."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed and role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------
def _pag_int(raw):
    if isinstance(raw, str):
        raw = raw.strip()
    if raw is None or raw == "":
        raise ApiError("ERR_INVALID_PAGINATION")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION")


def pagination():
    limit = 10
    offset = 0
    if "limit" in request.args:
        limit = _pag_int(request.args.get("limit"))
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in request.args:
        offset = _pag_int(request.args.get("offset"))
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def page(items, limit, offset):
    return items[offset:offset + limit]


def qfilter(items, mapping):
    """mapping: query-param name -> (row field, coercion)."""
    out = items
    for param, spec in mapping.items():
        if param not in request.args:
            continue
        raw = request.args.get(param)
        field, kind = spec
        if kind == "bool":
            low = str(raw).strip().lower()
            if low in ("true", "1", "yes"):
                wanted = True
            elif low in ("false", "0", "no"):
                wanted = False
            else:
                out = []
                continue
            out = [r for r in out if r.get(field) is wanted]
        else:
            out = [r for r in out if r.get(field) == raw]
    return out


# --------------------------------------------------------------------------
# field validation (all failures are ERR_INVALID_REQUEST unless stated)
# --------------------------------------------------------------------------
def bad(message=None):
    raise ApiError("ERR_INVALID_REQUEST", message)


def present(payload, field):
    return field in payload and payload[field] is not None


def vstr(payload, field, required=True, minlen=None, maxlen=None, default=None):
    if not present(payload, field):
        if required:
            bad("%s is required" % field)
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad("%s must be a string" % field)
    if minlen is not None and len(value) < minlen:
        bad("%s is too short" % field)
    if maxlen is not None and len(value) > maxlen:
        bad("%s is too long" % field)
    return value


def venum(payload, field, allowed, required=True, default=None):
    if not present(payload, field):
        if required:
            bad("%s is required" % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        bad("%s is not a permitted value" % field)
    return value


def vbool(payload, field, required=False, default=None):
    if not present(payload, field):
        if required:
            bad("%s is required" % field)
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % field)
    return value


def vint(payload, field, required=True, minimum=None, maximum=None, default=None):
    if not present(payload, field):
        if required:
            bad("%s is required" % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("%s is below the permitted minimum" % field)
    if maximum is not None and value > maximum:
        bad("%s is above the permitted maximum" % field)
    return value


def vnum(payload, field, required=True, minimum=None, maximum=None, default=None):
    if not present(payload, field):
        if required:
            bad("%s is required" % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % field)
    try:
        value = db.dec(value)
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % field)
    if minimum is not None and value < db.dec(minimum):
        bad("%s is below the permitted minimum" % field)
    if maximum is not None and value > db.dec(maximum):
        bad("%s is above the permitted maximum" % field)
    return value


def vdt(payload, field, required=True, default=None):
    if not present(payload, field):
        if required:
            bad("%s is required" % field)
        return default
    parsed = db.parse_dt(payload[field])
    if parsed is None:
        bad("%s must be an ISO-8601 instant" % field)
    return parsed


def vkeylist(payload, field, allowed, default=None):
    """Optional array of enum keys; duplicates are ERR_INVALID_REQUEST."""
    if not present(payload, field):
        return list(default or [])
    value = payload[field]
    if not isinstance(value, list):
        bad("%s must be an array" % field)
    seen = set()
    for item in value:
        if not isinstance(item, str):
            bad("%s members must be strings" % field)
        if item not in allowed:
            bad("%s contains an unknown key" % field)
        if item in seen:
            bad("%s contains a duplicate key" % field)
        seen.add(item)
    return list(value)


def vfkstr(payload, field, required=True):
    """Body FK shape check that must not pre-empt the 404 band: only rejects
    non-string values."""
    if not present(payload, field):
        return None
    value = payload[field]
    if not isinstance(value, str):
        return None
    return value


def bin_proportions(payload, field):
    """PRD 2.7 band 5: ERR_INVALID_BIN_PROPORTIONS in preference to
    ERR_INVALID_REQUEST."""
    if not present(payload, field):
        bad("%s is required" % field)
    value = payload[field]
    if not isinstance(value, list):
        bad("%s must be an array" % field)
    if len(value) != 5:
        raise ApiError("ERR_INVALID_BIN_PROPORTIONS")
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ApiError("ERR_INVALID_BIN_PROPORTIONS")
        d = db.dec(item)
        if d < 0 or d > 1:
            raise ApiError("ERR_INVALID_BIN_PROPORTIONS")
        out.append(d)
    total = sum(out, Decimal(0))
    if abs(total - Decimal(1)) > Decimal("0.0001"):
        raise ApiError("ERR_INVALID_BIN_PROPORTIONS")
    return out
