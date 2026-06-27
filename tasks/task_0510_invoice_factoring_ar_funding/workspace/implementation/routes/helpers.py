"""Shared route helpers: body parsing, lookups, sorted-list construction."""

from flask import request

import db
import errors
from middleware import paginate
from response import success


def get_body():
    """Parse JSON body; tolerate empty body for action endpoints."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        # An empty/blank body is acceptable for no-input action endpoints.
        if request.data.strip() in (b"", b"{}"):
            return {}
        raise errors.invalid_request("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def lookup(collection, resource_id):
    """Return the record or raise ERR_NOT_FOUND."""
    rec = collection.get(resource_id)
    if rec is None:
        raise errors.not_found("Resource not found")
    return rec


def sorted_by_created(records):
    """Stable ascending sort by created_at then creation sequence."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_response(records, view_fn=None):
    """Sort by created_at asc, paginate, serialise. view_fn defaults to public()."""
    from common import public
    ordered = sorted_by_created(records)
    page, meta = paginate(ordered)
    if view_fn is None:
        data = [public(r) for r in page]
    else:
        data = [view_fn(r) for r in page]
    return success(data, status=200, pagination=meta)
