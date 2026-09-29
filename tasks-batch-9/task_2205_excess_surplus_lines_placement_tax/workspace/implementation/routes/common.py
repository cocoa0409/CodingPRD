"""Shared helpers for the route blueprints."""

from flask import request

import serialize
from envelope import listing, pagination, paginate


def list_response(rows, mapper=None):
    """Rung 6 pagination validation, then the array envelope (PRD 2.3)."""
    limit, offset = pagination()
    total = len(rows)
    page = paginate(rows, limit, offset)
    fn = mapper or serialize.public
    return listing([fn(r) for r in page], limit, offset, total)


def arg(name):
    value = request.args.get(name, None)
    if value is None or value == "":
        return None
    return value


def filtered(rows, **filters):
    out = []
    for rec in rows:
        keep = True
        for key, value in filters.items():
            if value is None:
                continue
            if rec.get(key) != value:
                keep = False
                break
        if keep:
            out.append(rec)
    return out
