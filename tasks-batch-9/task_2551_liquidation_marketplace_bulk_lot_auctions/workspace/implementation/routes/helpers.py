"""Shared list/paginate helper for the read channels."""

from flask import request

import db
import response


def list_rows(kind, rows, filters=()):
    limit, offset = response.pagination_params()
    for param, field in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        rows = [row for row in rows if _matches(row.get(field), raw)]
    rows = db.ordered(rows)
    total = len(rows)
    page = response.window(rows, limit, offset)
    return response.collection(db.views(kind, page), limit, offset, total)


def _matches(value, raw):
    if value is None:
        return raw in ("", "null")
    if isinstance(value, bool):
        return raw.lower() == str(value).lower()
    return str(value) == raw
