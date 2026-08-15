"""Shared route helpers: serialization, list pagination, read auth."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import ANY_ROLES, authorized
from response import success_list, success_object
from validate import require_path_resource

# RFC 3339 timestamps sort chronologically as plain strings; creation order is
# the stable creation (created_at) order per PRD §2.3.
_FRACTIONAL = (0, 1)


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def get_one(collection, rid):
    """GET a single resource — open to any authenticated role (Any)."""
    authorized(ANY_ROLES)
    rec = require_path_resource(collection, rid)
    return success_object(public(rec))


def list_response(collection, filters):
    """List with created_at-ascending sort, exact-match filters, pagination.

    `filters` maps resource field name -> raw query value (None when absent).
    Integer-typed fields are coerced; unparsable values match nothing.
    """
    authorized(ANY_ROLES)
    limit, offset = get_pagination()
    items = sorted(
        db[collection].values(),
        key=lambda r: (r["created_at"], r["id"]),
    )
    for field, raw in filters.items():
        if raw is None:
            continue
        items = [r for r in items if field in r and _matches(r[field], raw)]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def _matches(stored, raw):
    if isinstance(stored, int) and not isinstance(stored, bool):
        try:
            return stored == int(raw)
        except (TypeError, ValueError):
            return False
    return str(stored) == raw
