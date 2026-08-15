"""Shared route helpers: serialization, list pagination, filters (PRD 2.2, 2.3)."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, check_role_allowed, READ_ROLES
from response import success_list, success_object
from validate import require_path_resource


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


def list_response(collection, filters=None, serializer=None):
    """List: auth (all roles), exact-match filters, created_at ascending, pagination."""
    caller = get_caller()
    check_role_allowed(caller, READ_ROLES)
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    ser = serializer or public
    return success_list([ser(r) for r in page], total, limit, offset)


def get_one(collection, rid, serializer=None):
    caller = get_caller()
    check_role_allowed(caller, READ_ROLES)
    rec = require_path_resource(collection, rid)
    ser = serializer or public
    return success_object(ser(rec))
