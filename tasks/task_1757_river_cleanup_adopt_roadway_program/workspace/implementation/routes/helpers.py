"""Shared route helpers: pagination, list responses, ownership-chain scoping."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import LEADER
from response import success_list
from services.core import public


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


def list_response(collection, caller, filters=None, owner_of=None):
    """List with created_at-ascending sort, exact-match query filters, optional
    GroupLeader chain scoping, and limit/offset pagination.

    owner_of: callable(record) -> owning AdopterGroup id or None. When the
    caller is a GroupLeader and owner_of is provided, the listing is silently
    scoped to the caller's own chains (PRD 2.1).
    """
    items = list(db[collection].values())
    if caller.role == LEADER and owner_of is not None:
        items = [r for r in items if owner_of(r) == caller.user_id]
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


def agreement_group_id(agreement):
    return agreement["group_id"] if agreement else None


def event_owner_group_id(ev):
    """Owning group of an event = its agreement's group."""
    ag = db["agreements"].get(ev["agreement_id"]) if ev else None
    return ag["group_id"] if ag else None


def agreement_chain_owner(agreement_id):
    ag = db["agreements"].get(agreement_id)
    return ag["group_id"] if ag else None


def hazard_owner_group_id(hz):
    """Hazards are owned through the referenced event's agreement only when an
    event_id was supplied on the report (PRD 2.1)."""
    if hz is None:
        return None
    event_id = hz.get("event_id")
    if not event_id:
        return None
    ev = db["events"].get(event_id)
    return event_owner_group_id(ev)
