"""Shared route helpers: authorization, list endpoints, single-get endpoints."""
from flask import request

from middleware import get_caller, require_roles, ALL_ROLES
from response import success_list, success_object
from serialize import public, public_list
from services.core import find_all, get_or_404
from validate import pagination_params


def authorize(roles):
    """Validation priorities 1-2: header presence, then role membership."""
    caller = get_caller()
    require_roles(caller, roles)
    return caller


def list_response(collection, filter_keys):
    limit, offset = pagination_params()
    filters = {}
    for key in filter_keys:
        v = request.args.get(key)
        if v is not None and v != "":
            filters[key] = v
    items = find_all(collection, **filters)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(public_list(page), total, limit, offset)


def get_response(collection, entity_id):
    ent = get_or_404(collection, entity_id)
    return success_object(public(ent))
