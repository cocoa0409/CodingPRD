"""Shared route helpers: path lookup, body-FK existence, pagination, list queries."""
from flask import request

from db import db
from errors import raise_error, ERR_NOT_FOUND, ERR_VALIDATION
from response import success_list
from services.core import public


def get_path(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"resource not found: {rid}")
    return rec


def check_site_fk(body):
    """Priority 3: a well-formed body-referenced site_id must exist (404).

    Runs before full field validation (priority 4). A missing or non-string
    site_id falls through to priority-4 field validation.
    """
    ref = body.get("site_id")
    if isinstance(ref, str) and ref.strip() and ref not in db["sites"]:
        raise_error(ERR_NOT_FOUND, "referenced site does not exist")


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def opt_query_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    from datetime import date
    try:
        date.fromisoformat(raw)
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, f"invalid ISO date query parameter: {name}")
    return raw


def list_query(collection, filters=None):
    """created_at-ascending list with equality filters and pagination."""
    items = list(db[collection].values())
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
