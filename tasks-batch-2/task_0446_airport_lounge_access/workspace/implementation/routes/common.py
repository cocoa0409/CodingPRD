"""Shared list helpers: filter, sort by creation order, paginate."""
from flask import request

import errors
from validation import parse_pagination, paginate
from serializers import serialize_list
from response import list_response


def sorted_by_creation(store):
    """All records of a store sorted ascending by creation (insertion) order."""
    records = list(store.items.values())
    records.sort(key=lambda r: r["_seq"])
    return records


def list_filtered(store, filter_specs):
    """filter_specs: list of (query_param, record_field, kind).
    kind in {"str", "bool"}. Returns a paginated list response.

    Unknown query params other than declared filters + limit/offset are ignored.
    """
    records = sorted_by_creation(store)

    for param, field, kind in filter_specs:
        if param in request.args:
            raw = request.args.get(param)
            if kind == "bool":
                low = raw.lower()
                if low in ("true", "1"):
                    want = True
                elif low in ("false", "0"):
                    want = False
                else:
                    raise errors.invalid_request("%s must be a boolean" % param)
                records = [r for r in records if r.get(field) == want]
            else:
                records = [r for r in records if r.get(field) == raw]

    limit, offset = parse_pagination()
    page, total = paginate(records, limit, offset)
    return list_response(serialize_list(page), limit, offset, total)
