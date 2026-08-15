"""Shared route helpers: pagination, list responses, scoped single-GET.

Tenant is the entity-backed role (PRD §2.1): on single-resource GETs the
resource's tenancy chain must match X-User-ID; on list GETs a Tenant sees
only records chained to their own tenancy. Jurisdiction profiles, properties,
and units carry no tenancy reference and are visible to every role.
"""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import ALL_ROLES, get_caller, check_role_allowed, check_tenant_ownership
from response import success_list, success_object
from services.core import public
from validate import require_path_resource


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


def tenancy_scope_of(collection, rec):
    """The tenancy id that scopes a record for Tenant ownership, or None when
    the entity carries no tenancy reference."""
    if rec is None:
        return None
    if collection == "tenancies":
        return rec["id"]
    if collection in ("jurisdiction_profiles", "properties", "units"):
        return None
    if collection == "inspection_items":
        insp = db["inspections"].get(rec.get("inspection_id"))
        return insp["tenancy_id"] if insp else None
    return rec.get("tenancy_id")


def get_one(collection, rid):
    """GET one resource: auth (1) -> role (2) -> existence (4) -> tenant
    ownership for entity-backed callers."""
    caller = get_caller()
    check_role_allowed(caller, ALL_ROLES)
    rec = require_path_resource(collection, rid)
    check_tenant_ownership(caller, tenancy_scope_of(collection, rec))
    return success_object(public(rec))


def list_response(collection, filters=None):
    """List with created_at-ascending sort, query filters, Tenant scoping,
    and limit/offset pagination (PRD §2.3)."""
    caller = get_caller()
    check_role_allowed(caller, ALL_ROLES)
    items = list(db[collection].values())
    if caller.role == "Tenant":
        items = [r for r in items
                 if tenancy_scope_of(collection, r) in (None, caller.user_id)]
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
