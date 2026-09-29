"""Shared listing helpers for collection reads (PRD 2.3)."""

from flask import request

import middleware
import response
from db import public, sort_rows


def apply_filters(rows, names):
    selected = rows
    for name in names:
        raw = request.args.get(name)
        if raw is None or raw == "":
            continue
        selected = [row for row in selected if _matches(row.get(name), raw)]
    return selected


def _matches(value, raw):
    if value is None:
        return False
    if isinstance(value, bool):
        return ("true" if value else "false") == raw.lower()
    return str(value) == raw


def paged(rows, primary=None, filters=()):
    limit, offset = middleware.parse_paging()
    rows = apply_filters(rows, filters)
    rows = sort_rows(rows, primary)
    total = len(rows)
    window = rows[offset:offset + limit]
    return response.list_response(
        [public(row) for row in window], limit, offset, total
    )
