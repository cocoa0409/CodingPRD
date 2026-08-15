"""Shared route helpers: path existence, pagination, list envelopes."""
from db import db
from errors import raise_error
from response import success_list
from validate import get_pagination


def require(collection, rid, err_spec, message=""):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(err_spec, message or f"{collection} id does not exist")
    return rec


def list_envelope(items, view=None):
    """Sort by created_at ascending (PRD 2.3), paginate, wrap in the array envelope."""
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    if view is not None:
        page = [view(r) for r in page]
    else:
        page = [dict(r) for r in page]
    return success_list(page, total, limit, offset)
