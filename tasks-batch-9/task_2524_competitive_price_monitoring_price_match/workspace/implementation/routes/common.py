"""Shared route helpers: path/body identifier resolution and list plumbing."""
from flask import request

import db
from errors import err
from response import array_response, pagination, paginate

# The body foreign-key declaration order of PRD 2.10.
FK_POLICY = ("policy_id", "policies", "ERR_POLICY_NOT_FOUND")
FK_PRODUCT = ("product_id", "products", "ERR_PRODUCT_NOT_FOUND")
FK_COMPETITOR = ("competitor_id", "competitors", "ERR_COMPETITOR_NOT_FOUND")
FK_STORE = ("store_id", "stores", "ERR_STORE_NOT_FOUND")
FK_SIGNAGE_STORE = ("signage_store_id", "stores", "ERR_STORE_NOT_FOUND")
FK_LINK = ("link_id", "links", "ERR_MATCH_NOT_FOUND")
FK_MARKET = ("market_id", "markets", "ERR_MARKET_NOT_FOUND")
FK_SUPERSEDES = ("supersedes_order_id", "orders", "ERR_ORDER_NOT_FOUND")


def path_lookup(collection_name, identifier, error_id):
    """Resolve a path identifier; raise the 404 of PRD 2.10 when it is unknown."""
    record = getattr(db, collection_name).get(identifier)
    if record is None:
        raise err(error_id, "%s does not name a live resource." % identifier)
    return record


def resolve_fks(payload, specs):
    """Resolve body foreign keys in the fixed declaration order of PRD 2.10.

    A field that is absent or null is skipped here — its required-ness is a
    rank-5 concern that runs after every declared foreign key has resolved.
    """
    resolved = {}
    for name, collection_name, error_id in specs:
        raw = payload.get(name) if isinstance(payload, dict) else None
        if raw is None:
            resolved[name] = None
            continue
        record = None
        if isinstance(raw, str):
            record = getattr(db, collection_name).get(raw)
        if record is None:
            raise err(error_id, "%s '%s' does not name a live resource."
                      % (name, raw))
        resolved[name] = record
    return resolved


def filtered(rows, args, field_filters):
    """Conjunctive equality filters read from the query string (PRD 2.3)."""
    out = rows
    for param, field in field_filters:
        value = args.get(param)
        if value is None:
            continue
        out = [r for r in out if str(r.get(field)) == value]
    return out


def list_page(rows, serializer):
    limit, offset = pagination(request.args)
    page = paginate(rows, limit, offset)
    return array_response([serializer(r) for r in page], limit, offset, len(rows))
