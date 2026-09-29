"""Shared route helpers."""
from db import created_order
from errors import ApiError
from response import listing, pagination_params, paginate, serialize


def list_out(rows, order="created"):
    """PRD 2.3: validate pagination, order, then slice."""
    limit, offset = pagination_params()
    if order == "created":
        rows = created_order(rows)
    elif order == "created_desc":
        rows = list(reversed(created_order(rows)))
    elif order == "sequence":
        rows = sorted(rows, key=lambda r: (r["sequence_index"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)


def match(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def date_range(start, end):
    """PRD 2.8: end_date must be strictly after start_date."""
    if start is None or end is None:
        return
    if not end > start:
        raise ApiError("ERR_INVALID_DATE_RANGE")


def out(row):
    return serialize(row)
