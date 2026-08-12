"""Shared route helpers."""

from flask import request

from errors import not_found
from response import ok_list
from util import pagination_params, to_public


def get_or_404(table, rid, label="Resource"):
    rec = table.get(rid)
    if rec is None:
        raise not_found(f"{label} '{rid}' does not exist")
    return rec


def list_response(records, filters):
    """filters: list of (query_param, record_field) exact-match filters."""
    items = []
    for rec in records:
        ok = True
        for param, field in filters:
            val = request.args.get(param)
            if val is not None and str(rec.get(field)) != val:
                ok = False
                break
        if ok:
            items.append(rec)
    # PRD 2.3: sorted by created_at ascending; _seq breaks same-ms ties
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([to_public(r) for r in page], limit, offset, total)
