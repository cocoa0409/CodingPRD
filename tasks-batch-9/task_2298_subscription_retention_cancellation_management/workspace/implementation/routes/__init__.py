"""Shared list-endpoint helpers."""
from flask import request

from db import ordered
from response import listing, paginate


def filtered(records, spec):
    """spec maps query-parameter name -> record field name."""
    rows = list(records)
    for param, field in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        rows = [r for r in rows if r.get(field) is not None and str(r.get(field)) == raw]
    return rows


def send_list(records, serializer, spec=None):
    rows = filtered(ordered(records), spec or {})
    page, limit, offset, total = paginate(request.args, rows)
    return listing([serializer(r) for r in page], limit, offset, total)
