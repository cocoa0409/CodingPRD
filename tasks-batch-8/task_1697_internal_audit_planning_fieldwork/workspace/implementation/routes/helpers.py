"""Shared route helpers: read-role set, pagination, filtered list responses."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import ALL_ROLES, authorized
from response import success_list, success_object
from services.core import public


def get_pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0) — PRD 2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
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


def get_one(collection, rid, pre=None):
    """GET-by-id: auth stages 1-3, then existence (stage 4)."""
    from validate import require_path
    authorized(ALL_ROLES)
    rec = require_path(collection, rid)
    if pre is not None:
        pre(rec)
    return success_object(public(rec))


def list_response(collection, filters=None, pre=None):
    """List: auth stages 1-3, equality filters, created_at-ascending sort,
    limit/offset pagination (PRD 2.3)."""
    authorized(ALL_ROLES)
    items = list(db[collection].values())
    if pre is not None:
        for rec in items:
            pre(rec)
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def query_int(name):
    """Optional integer query filter (e.g. fiscal_year); invalid -> 400."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, f"query parameter {name} must be an integer")


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
