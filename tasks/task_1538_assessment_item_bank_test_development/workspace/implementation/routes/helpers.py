"""Shared route helpers: serialization, pagination, filtered listing."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from response import success_list, success_object


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


def _matches(rec, filters):
    for field, value in filters.items():
        if value is None:
            continue
        if isinstance(value, bool):
            if rec.get(field) != value:
                return False
        elif field == "section_index" or field == "excluded":
            if str(rec.get(field)) != str(value):
                return False
        else:
            if rec.get(field) != value:
                return False
    return True


def list_response(collection, filters=None, exclude=None):
    """List with created_at-ascending sort, exact-match query filters, pagination."""
    items = list(db[collection].values())
    if filters:
        items = [r for r in items if _matches(r, filters)]
    if exclude is not None:
        items = [r for r in items if exclude(r)]
    items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(rec):
    return success_object(public(rec))


def truthy_param(name):
    raw = request.args.get(name)
    if raw is None:
        return False
    return raw.strip().lower() in ("true", "1", "yes")


def bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None
