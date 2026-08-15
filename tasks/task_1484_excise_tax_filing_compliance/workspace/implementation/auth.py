"""Auth header extraction, role authorization, body parsing, field validators,
pagination parsing, and common serialization helpers."""
import json

from flask import request

import errors
from errors import raise_err
from store import DB, new_id
from utiltime import now_iso, parse_dt

ROLES = {"ComplianceAdmin", "TaxAnalyst", "TaxReviewer", "JurisdictionAuditor", "System"}
CLIENT_ROLES = {"ComplianceAdmin", "TaxAnalyst", "TaxReviewer", "JurisdictionAuditor"}
ALL_READ_ROLES = ["ComplianceAdmin", "TaxAnalyst", "TaxReviewer", "JurisdictionAuditor"]


# ---------------------------------------------------------------- auth
def current_user():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None:
        raise_err(errors.ERR_AUTH, "X-User-ID and X-User-Role headers are required")
    if not isinstance(uid, str) or not uid.strip():
        raise_err(errors.ERR_AUTH, "X-User-ID header is missing or malformed")
    if not isinstance(role, str) or role not in ROLES:
        raise_err(errors.ERR_AUTH, "X-User-Role header is missing or names an undeclared role")
    return uid, role


def require_roles(allowed):
    _uid, role = current_user()
    if role not in allowed:
        raise_err(errors.ERR_FORBIDDEN, "Caller role is not authorized for this endpoint")
    return _uid, role


def user_id():
    uid, _role = current_user()
    return uid


# ---------------------------------------------------------------- body
def body_dict(require=True):
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        if require:
            raise_err(errors.ERR_INVALID_REQUEST, "Request body is not well-formed JSON")
        return {}
    if not isinstance(data, dict):
        if require:
            raise_err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return {}
    return data


def _bad(msg):
    raise_err(errors.ERR_INVALID_REQUEST, msg)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        _bad(f"Field '{name}' is required and must be a non-empty string")
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(f"Field '{name}' must be a string")
    return v


def req_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(f"Field '{name}' is required and must be an integer")
    if minimum is not None and v < minimum:
        _bad(f"Field '{name}' must be at least {minimum}")
    return v


def opt_int(body, name, default=None, minimum=None):
    if name not in body or body.get(name) is None:
        return default
    return req_int(body, name, minimum)


def req_enum(body, name, values):
    v = body.get(name)
    if not isinstance(v, str) or v not in values:
        _bad(f"Field '{name}' must be one of {sorted(values)}")
    return v


def opt_bool(body, name, default=False):
    v = body.get(name, default)
    if not isinstance(v, bool):
        _bad(f"Field '{name}' must be a boolean")
    return v


def req_dt(body, name):
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        _bad(f"Field '{name}' is required and must be an ISO 8601 datetime")
    return dt


def opt_dt(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    return req_dt(body, name)


def req_str_list(body, name):
    v = body.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(f"Field '{name}' is required and must be an array of strings")
    return v


# ---------------------------------------------------------------- pagination
def pagination_params():
    def _as_int(raw, default):
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise_err(errors.ERR_INVALID_REQUEST, "Pagination parameters must be integers")
    limit = _as_int(request.args.get("limit"), 10)
    offset = _as_int(request.args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, serializer, sort_key=None):
    """items: list of entity dicts. Sorts, paginates, serializes."""
    if sort_key is None:
        sort_key = lambda e: (e["created_at"], e.get("_seq", 0))
    ordered = sorted(items, key=sort_key)
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(e) for e in page], limit, offset, total


# ---------------------------------------------------------------- entities
def new_entity(extra):
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    ent.update(extra)
    return ent


def touch(ent):
    """Mark a mutation: refresh updated_at, bump version."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1


def touch_if_changed(ent, changes):
    """Apply computed-field changes; counts as a mutation only when a value moved."""
    changed = False
    for k, v in changes.items():
        if ent.get(k) != v:
            ent[k] = v
            changed = True
    if changed:
        touch(ent)
    return changed


def get_or_404(table, entity_id, label="Resource"):
    ent = table.get(entity_id)
    if ent is None:
        raise_err(errors.ERR_NOT_FOUND, f"{label} '{entity_id}' was not found")
    return ent


def public(ent, fields):
    """Serialize an entity: common fields + declared fields (internal _* skipped)."""
    out = {
        "id": ent["id"],
        "created_at": ent["created_at"],
        "updated_at": ent["updated_at"],
        "version": ent["version"],
    }
    for f in fields:
        if f in ent:
            out[f] = ent[f]
    return out
