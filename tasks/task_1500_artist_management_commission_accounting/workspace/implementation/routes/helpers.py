"""Shared route helpers: serialization, list pagination, artist-chain scoping."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import (
    authorized, get_caller, check_role_allowed, resolve_entity_backed,
    check_artist_scope, check_team_active,
)
from response import success_list, success_object
from validate import require_path_resource

ALL_READ_ROLES = ["FirmAdmin", "Agent", "BusinessManager", "Publicist", "Artist", "Auditor"]


def serialize(collection, rec):
    return dict(rec) if rec is not None else None


def public(rec):
    if rec is None:
        return None
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    return out


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


def list_response(collection, filters=None, scope_artist_field="artist_id"):
    """List with created_at-ascending sort, query filters, caller scoping, pagination."""
    caller = get_caller()
    check_role_allowed(caller, ALL_READ_ROLES)
    resolve_entity_backed(caller)
    check_team_active(caller)

    items = list(db[collection].values())
    # Scope: entity-backed callers see only their artist's records
    if caller.role in ("Agent", "BusinessManager", "Publicist", "Artist"):
        scope = caller.artist_scope_id
        if collection == "artists":
            items = [a for a in items if a["id"] == scope]
        elif scope_artist_field:
            items = [r for r in items if r.get(scope_artist_field) == scope]
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(collection, rid, artist_id_field="artist_id"):
    """GET one resource with auth priorities 1-6 (scoping after existence)."""
    caller = get_caller()
    check_role_allowed(caller, ALL_READ_ROLES)
    resolve_entity_backed(caller)
    rec = require_path_resource(collection, rid)
    # Determine artist chain for scoping
    if collection == "artists":
        scope_artist = rec["id"]
    elif collection == "team_members":
        scope_artist = rec["artist_id"]
    else:
        scope_artist = rec.get(artist_id_field)
    check_artist_scope(caller, scope_artist)
    check_team_active(caller)
    return success_object(public(rec))


def artist_chain_for(collection, rec):
    """Resolve the artist_id that scopes a resource for priority-3 checks."""
    if rec is None:
        return None
    if collection == "artists":
        return rec["id"]
    if collection == "agreements":
        return rec.get("artist_id")
    if collection == "rate_schedules":
        ag = db["agreements"].get(rec.get("agreement_id"))
        return ag.get("artist_id") if ag else None
    return rec.get("artist_id")


def scoped_mutation_auth(allowed_roles, collection=None, rid=None, body_artist_id=None):
    """Auth for mutations: 1) headers, 2) role, 3) scope vs target artist chain,
    4) team-member status. Path existence (priority 6) is handled by callers after
    body-shape validation (priority 5)."""
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    resolve_entity_backed(caller)
    # Scope check: use body's artist_id on creates, else the target resource chain
    if body_artist_id is not None:
        check_artist_scope(caller, body_artist_id)
    elif collection is not None and rid is not None:
        rec = db[collection].get(rid)
        if rec is not None:
            check_artist_scope(caller, artist_chain_for(collection, rec))
    check_team_active(caller)
    return caller
