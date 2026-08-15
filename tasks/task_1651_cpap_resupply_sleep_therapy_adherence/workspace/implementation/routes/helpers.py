"""Shared read-path helpers: serializers, get-one, paginated list (PRD 2.2/2.3)."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized, ALL_ROLES
from response import success_object, success_list
from services.core import public, compute_outstanding_balance_cents


def serialize(collection, rec):
    out = public(rec)
    if collection == "patients":
        # Computed aggregate: sum of INVOICED orders' patient responsibility.
        out["outstanding_balance_cents"] = compute_outstanding_balance_cents(rec["id"])
    return out


def get_one(collection, rid):
    authorized(ALL_ROLES)
    rec = db[collection].get(rid)
    if rec is None:
        from errors import ERR_NOT_FOUND
        raise_error(ERR_NOT_FOUND, f"{collection} resource not found: {rid}")
    return success_object(serialize(collection, rec))


def _parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(collection, filters):
    """filters: {field: raw_query_value}; None values mean 'no filter'."""
    authorized(ALL_ROLES)
    limit, offset = _parse_pagination()
    items = sorted(
        (r for r in db[collection].values() if _matches(r, filters)),
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(collection, r) for r in page], total, limit, offset)


def _matches(rec, filters):
    for field, value in filters.items():
        if value is None:
            continue
        if rec.get(field) != value:
            return False
    return True
