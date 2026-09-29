"""Filtered / sorted / paginated collection responses (PRD 2.3, 2.9)."""
from flask import request

import db
import middleware
import response


def sort_created_asc(rows):
    rows.sort(key=db.sort_key_created)
    return rows


def sort_created_desc(rows):
    rows.sort(key=db.sort_key_created, reverse=True)
    return rows


def sort_by(rows, primary):
    rows.sort(key=lambda r: (r.get(primary) or "", r.get("created_at") or "", r.get("_seq") or 0))
    return rows


def apply_filters(rows, allowed):
    """Conjunctive equality filters drawn from the query string."""
    for name in allowed:
        value = request.args.get(name)
        if value is None:
            continue
        rows = [r for r in rows if str(r.get(name)) == value]
    return rows


def page(rows):
    limit, offset = middleware.pagination()
    items, total = middleware.paginate(rows, limit, offset)
    return response.paginated(db.serialize_all(items), limit, offset, total)
