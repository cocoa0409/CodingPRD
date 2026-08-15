"""Shared route helpers: pagination, list filtering, read endpoints."""
from flask import request

from db import db
from errors import raise_error, ERR_VALIDATION
from middleware import authorized, ALL_ROLES
from response import success_list, success_object
from validate import require_path_resource


def get_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
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


def _matches(rec, filters):
    for field, value in filters.items():
        if value is None:
            continue
        cur = rec.get(field)
        if cur is None or str(cur) != value:
            return False
    return True


def list_response(collection, serializer, filters, sort_key=None):
    """All seven roles may read any resource. Sorted by created_at ascending
    (insertion sequence tiebreak); units additionally tiebreak by line_no."""
    authorized(ALL_ROLES)
    items = [r for r in db[collection].values() if _matches(r, filters)]
    if sort_key is None:
        items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    else:
        items.sort(key=sort_key)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


def get_one(collection, serializer, rid):
    authorized(ALL_ROLES)
    rec = require_path_resource(collection, rid)
    return success_object(serializer(rec))
