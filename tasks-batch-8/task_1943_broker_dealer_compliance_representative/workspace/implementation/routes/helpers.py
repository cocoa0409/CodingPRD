"""Shared route helpers: list pagination + filtering, single-resource reads."""
from flask import request

from db import db
from errors import raise_error, ERR_VALIDATION
from middleware import authorized, READ_ROLES
from response import success_list, success_object
from services.core import by_creation, public
from validate import require_path_resource

# pagination defaults per SCAFFOLD 1.0 / PRD 2.3
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
        if isinstance(limit, bool) or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_error(ERR_VALIDATION, f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset_raw is None or offset_raw == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def list_response(collection, filters=None):
    """List with created_at-ascending (creation-order) sort, exact-match query
    filters, and limit/offset pagination. All GET endpoints allow any role."""
    authorized(READ_ROLES)
    items = by_creation(list(db[collection].values()))
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(collection, rid):
    authorized(READ_ROLES)
    rec = require_path_resource(collection, rid)
    return success_object(public(rec))
