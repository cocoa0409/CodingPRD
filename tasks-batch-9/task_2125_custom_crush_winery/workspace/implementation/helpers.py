"""Shared helpers for the route modules: listing, filtering, action dispatch."""

from decimal import Decimal

from flask import request

from auth import CLIENT_REP
from envelope import respond_list
from errors import ApiError, ERR_INVALID_STATE
from store import sort_key
from validation import paginate, v_pagination

D = Decimal


def _as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _matches(stored, raw):
    if stored is None:
        return False
    if isinstance(stored, bool):
        return _as_text(stored) == str(raw).lower()
    if isinstance(stored, int):
        try:
            return int(str(raw)) == stored
        except Exception:
            return False
    if isinstance(stored, Decimal):
        try:
            return D(str(raw)) == stored
        except Exception:
            return False
    return str(stored) == str(raw)


def run_list(entities, ctx, serializer, owner_fn=None, filters=()):
    """Paginated, filtered, created_at-ascending listing."""
    limit, offset = v_pagination(request.args)
    items = sorted(entities, key=sort_key)
    if ctx.role == CLIENT_REP and owner_fn is not None:
        items = [e for e in items if owner_fn(e) == ctx.user_id]
    for param, field in filters:
        raw = request.args.get(param)
        if raw is not None and raw != "":
            items = [e for e in items if _matches(e.get(field), raw)]
    page, total = paginate(items, limit, offset)
    return respond_list([serializer(e) for e in page], limit, offset, total)


def declared(condition, message="The requested action is not declared out of the "
                                "target's current state."):
    """Ladder rung 30 -- terminal-state lockdown and repeat-trigger rejection."""
    if not condition:
        raise ApiError(ERR_INVALID_STATE, message)


def require_state(entity, field, allowed):
    if entity.get(field) not in allowed:
        raise ApiError(ERR_INVALID_STATE,
                       "Current %s '%s' does not permit this action."
                       % (field, entity.get(field)))
