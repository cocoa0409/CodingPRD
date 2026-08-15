"""Shared route helpers: pagination, lookup, error registration."""
from flask import request

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION_FAILED
from response import success_list
from middleware import ANY_AUTHENTICATED, require_roles


def paginate(items):
    """Apply limit/offset pagination per the scaffold envelope spec."""
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION_FAILED, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_VALIDATION_FAILED, "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError(ERR_VALIDATION_FAILED, "offset must be >= 0", 400)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, total, limit, offset)


def lookup(store, resource_id, label="Resource"):
    ent = store.get(resource_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, f"{label} not found: {resource_id}", 404)
    return ent


def any_authenticated():
    return require_roles(ANY_AUTHENTICATED)
