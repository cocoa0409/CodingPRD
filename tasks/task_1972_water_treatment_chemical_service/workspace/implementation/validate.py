"""Body shape validation (tier 5), FK resolution (tier 4), pagination,
and CustomerContact ownership helpers (tier 3)."""

from flask import request

import errors
from db import db, parse_iso


# ---------------------------------------------------------------------------
# Request body access
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise errors.invalid_request("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Tier 5: shape validation
# ---------------------------------------------------------------------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and v == v and v not in (float("inf"), float("-inf")))


def check_type(name, value, ftype, enum=None):
    if ftype == "str":
        if not isinstance(value, str):
            raise errors.invalid_request("Field '%s' must be a string" % name)
    elif ftype == "int":
        if not _is_int(value):
            raise errors.invalid_request("Field '%s' must be an integer" % name)
    elif ftype == "num":
        if not _is_num(value):
            raise errors.invalid_request("Field '%s' must be a number" % name)
    elif ftype == "bool":
        if not isinstance(value, bool):
            raise errors.invalid_request("Field '%s' must be a boolean" % name)
    elif ftype == "iso":
        if not isinstance(value, str):
            raise errors.invalid_request("Field '%s' must be an ISO 8601 timestamp string" % name)
        try:
            parse_iso(value)
        except (ValueError, TypeError):
            raise errors.invalid_request("Field '%s' must be a valid ISO 8601 timestamp" % name)
    if enum is not None and value not in enum:
        raise errors.invalid_request("Field '%s' must be one of %s" % (name, sorted(enum)))


def validate_shape(body, specs, missing_error=None):
    """specs: list of (name, type, required, enum). Returns dict of parsed values.

    missing_error: optional ApiError factory for missing required fields
    (overrides the default ERR_INVALID_REQUEST, e.g. ERR_INCOMPLETE_DESIGN).
    """
    out = {}
    for spec in specs:
        name, ftype, required = spec[0], spec[1], spec[2]
        enum = spec[3] if len(spec) > 3 else None
        if name not in body or body[name] is None:
            if required:
                if missing_error is not None:
                    raise missing_error()
                raise errors.invalid_request("Missing required field '%s'" % name)
            out[name] = None
            continue
        value = body[name]
        check_type(name, value, ftype, enum)
        out[name] = parse_iso(value) if ftype == "iso" else value
    return out


# ---------------------------------------------------------------------------
# Tier 4: existence / foreign-key resolution
# ---------------------------------------------------------------------------

def resolve(kind, ident):
    """Resolve a path or body identifier to an entity, or 404."""
    ent = db[kind].get(ident) if isinstance(ident, str) else None
    if ent is None:
        raise errors.not_found()
    return ent


def resolve_body_fk(body, name, kind):
    """Body FK fields resolve in declared input order. Missing fields are left
    to the tier-5 shape check; present-but-unresolvable values yield 404."""
    if name not in body or body[name] is None:
        return None
    return resolve(kind, body[name])


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def parse_pagination():
    def _int_arg(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _int_arg("limit", 10)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    offset = _int_arg("offset", 0)
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items: full sorted list. Returns (page_items, limit, offset, total)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Tier 3: CustomerContact ownership
# ---------------------------------------------------------------------------

def check_cc_ownership(user_id, role, account_id):
    """For CustomerContact callers, X-User-ID must equal the owning account id."""
    if role == "CustomerContact" and user_id != account_id:
        raise errors.forbidden()


def cc_scope(role, user_id, items, account_of):
    """Scope a list to the caller's own account subtree for CustomerContact."""
    if role != "CustomerContact":
        return items
    return [e for e in items if account_of(e) == user_id]
