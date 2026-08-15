"""Shared route helpers: fetch-or-404, list responses."""
from flask import request

import errors
from envelope import ok_list, paginate
from store import STORE


def get_or_404(collection_name, rid, err_pair, message):
    rec = STORE.__dict__[collection_name].get(rid)
    if rec is None:
        errors.raise_err(err_pair, message)
    return rec


def list_response(records, serializer, paginated):
    """Serialize a list; paginated lists honor limit/offset, others return all
    with the pagination meta fields still present."""
    items = [serializer(r) for r in records]
    if paginated:
        page, limit, offset, total = paginate(items, request.args)
        return ok_list(page, limit, offset, total)
    total = len(items)
    return ok_list(items, total, 0, total)


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def sort_parcel_number(records):
    """Parcel / parcel-assessment listings order by parcel_number ASC."""
    def key(r):
        parcel = STORE.parcels.get(r.get("parcel_id")) if "parcel_id" in r else r
        pn = parcel["parcel_number"] if parcel else ""
        return (pn, r["created_at"], r.get("_seq", 0))
    return sorted(records, key=key)


def sort_due_date(records):
    return sorted(records,
                  key=lambda r: (r["due_date"], r["created_at"], r.get("_seq", 0)))
