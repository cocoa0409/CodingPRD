"""Shared request helpers: auth, RBAC, body parsing, validation, pagination."""
from flask import request

import store
from errors import err

KNOWN_ROLES = {"Registrar", "Coordinator", "Approver", "BillingAdmin", "Client"}


# ---------------------------------------------------------------------------
# Auth (priority 1) and role authorization (priority 2)
# ---------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or invalid authentication headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)


def auth(allowed_roles):
    """Authenticate then authorize against allowed_roles. Returns (uid, role)."""
    uid, role = require_auth()
    require_role(role, allowed_roles)
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing / field validation (priority 5)
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "request body must be a JSON object")
    return body


def require_fields(body, names):
    for name in names:
        if body.get(name) is None:
            raise err("ERR_VALIDATION", "missing required field: %s" % name)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_VALIDATION", "invalid %s: %r" % (field, value))


def require_int(body, name):
    v = body.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION", "field %s must be an integer" % name)
    return v


def require_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", "field %s must be a number" % name)
    return v


def require_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", "field %s must be a boolean" % name)
    return v


# ---------------------------------------------------------------------------
# Existence (priority 4)
# ---------------------------------------------------------------------------
def get_or_404(collection, rid):
    rec = store.db[collection].get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found: %s" % (collection, rid))
    return rec


def fk_or_404(collection, rid):
    """Validate a referenced foreign-key id exists."""
    if rid is None:
        return None
    rec = store.db[collection].get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "referenced %s not found: %s" % (collection, rid))
    return rec


# ---------------------------------------------------------------------------
# Pagination (§2.3) and listing
# ---------------------------------------------------------------------------
def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "%s must be an integer" % name)


def get_pagination():
    limit = _int_arg("limit", 10)
    offset = _int_arg("offset", 0)
    # clamp into declared bounds: limit in [1,100], offset >= 0
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records):
    """records: list of raw record dicts. Sort by creation order, window, serialize."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    limit, offset = get_pagination()
    window = ordered[offset:offset + limit]
    return [store.serialize(r) for r in window], limit, offset, total
