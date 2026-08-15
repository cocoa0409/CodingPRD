"""Shared route helpers: request body, pagination, list rendering with
filters and Contractor scoping (PRD 2.1/2.3/2.9)."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized, check_contractor_owns
from response import success_list, success_object
from services.core import pub, contractor_of


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def body_field(data, name, required=False, default=None):
    value = data.get(name, default)
    if required and value is None:
        raise_error(ERR_INVALID_REQUEST, f"{name} is required")
    return value


def require_int(value, name, minimum=None):
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, f"{name} must be an integer")
    if minimum is not None and ivalue < minimum:
        raise_error(ERR_INVALID_REQUEST, f"{name} must be >= {minimum}")
    return ivalue


def get_pagination():
    """limit defaults to 10, minimum 1, clamped at 100; offset defaults to 0
    (PRD 2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw in (None, ""):
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw in (None, ""):
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def render_list(caller, collection, filters=None, scope_collection=None,
                base_records=None):
    """created_at ascending (insertion order tie-break), exact-match filters,
    Contractor list scoping to own records, then pagination (PRD 2.3)."""
    items = list(base_records) if base_records is not None else list(db[collection].values())
    if caller.role == "Contractor":
        scope_coll = scope_collection or collection
        items = [r for r in items
                 if contractor_of(scope_coll, r) == caller.user_id]
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) is not None
                     and str(r.get(field)) == str(value)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([pub(collection, r) for r in page], total, limit, offset)


def render_one(collection, rec, status=200):
    return success_object(pub(collection, rec), status=status)
