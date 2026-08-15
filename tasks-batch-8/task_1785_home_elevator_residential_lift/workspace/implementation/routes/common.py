"""Shared helpers for route handlers: existence lookups (priority 3),
list-endpoint filtering/pagination, and ownership checks."""

from flask import request

import db
from errors import ApiError, ERR_NOT_PROPERTY_OWNER, not_found
from response import ok_list, paginate
from util import serialize_list, sorted_by_created


def get_or_404(store, rec_id, error_id, what):
    rec = store.get(rec_id)
    if rec is None:
        raise not_found(error_id, what)
    return rec


def list_endpoint(store, filters):
    """filters: dict query_param -> record field. Equality match; params absent
    or records with null field values simply do not match a supplied filter."""
    recs = list(store.values())
    for param, field in filters.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        recs = [r for r in recs if r.get(field) is not None and str(r.get(field)) == raw]
    recs = sorted_by_created(recs)
    limit, offset, total, page = paginate(recs, request.args)
    return ok_list(serialize_list(page), limit, offset, total)


def require_property_ownership(property_id):
    """Homeowner ownership binding: X-User-ID must equal Property.owner_user_id."""
    from flask import g

    prop = db.properties.get(property_id)
    if prop is None or g.user_id != prop["owner_user_id"]:
        raise ApiError(ERR_NOT_PROPERTY_OWNER, 403, "Caller does not own the property behind this resource")
