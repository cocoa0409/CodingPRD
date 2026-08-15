"""Shared route helpers: filtered + paginated list responses with scoping."""

from flask import request

from middleware import require_roles, enforce_client_scope
from response import success, parse_pagination, paginate_list
from services import domain


def do_list(store_values, serializer, filters, user_id, role, kind):
    """filters: list of (query_param, entity_field, transform) tuples.
    ClientContact sees only resources whose client_id == X-User-ID."""
    items = list(store_values)
    for param, field, transform in filters:
        raw = request.args.get(param, None)
        if raw is None:
            continue
        value = transform(raw) if transform else raw
        items = [e for e in items if e.get(field) == value]
    if role == "ClientContact":
        items = [e for e in items
                 if domain.client_id_for_resource(kind, e) == user_id]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate_list(items, limit, offset)
    return success([serializer(e) for e in page], 200, pagination)


def do_get(store, resource_id, serializer, user_id, role, kind, allowed_roles, not_found_msg):
    from errors import raise_error, ERR_NOT_FOUND
    require_roles(*allowed_roles)
    ent = store.get(resource_id)
    if ent is None:
        raise_error(ERR_NOT_FOUND, not_found_msg)
    enforce_client_scope(user_id, role, domain.client_id_for_resource(kind, ent))
    return success(serializer(ent), 200)


def bool_param(raw):
    return raw.strip().lower() in ("true", "1", "yes")
