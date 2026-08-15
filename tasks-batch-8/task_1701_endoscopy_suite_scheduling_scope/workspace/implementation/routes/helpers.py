"""Shared route helpers: pagination, list responses, single-resource reads."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized, ALL_READ_ROLES
from response import success_list, success_object
from services.core import public_for, sort_key
from validate import require_path_resource


def get_pagination():
    """PRD 2.3: limit default 10 (min 1, max 100), offset default 0."""
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


def list_response(collection, filters=None):
    """All-role GET list: created_at ascending (write order on ties), filters,
    pagination envelope."""
    authorized(ALL_READ_ROLES)
    items = list(db[collection].values())
    for field, value in (filters or {}).items():
        if value is None:
            continue
        items = [r for r in items if r.get(field) == value]
    items.sort(key=sort_key)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_for(collection, r) for r in page], total, limit, offset)


def get_one(collection, rid, not_found_spec):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource(collection, rid, not_found_spec)
    return success_object(public_for(collection, rec))
