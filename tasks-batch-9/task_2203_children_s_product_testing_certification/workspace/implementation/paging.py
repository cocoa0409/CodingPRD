"""List helpers: filtering, the documented sort orders and offset pagination."""

import db
import response
import validation


def filtered(table, predicates):
    rows = []
    for row in db.all_rows(table):
        if all(pred(row) for pred in predicates):
            rows.append(row)
    return rows


def eq_filter(field, value):
    if value is None:
        return None
    return lambda row: row.get(field) == value


def build(table, filters, sort="created_at_asc"):
    predicates = [f for f in filters if f is not None]
    rows = filtered(table, predicates)
    if sort == "material_change_desc":
        rows.sort(key=lambda r: (r["occurred_at"], r["created_at"]), reverse=True)
    else:
        rows.sort(key=lambda r: r["created_at"])
    limit, offset = validation.pagination()
    total_count = len(rows)
    page = rows[offset:offset + limit]
    return response.list_response(
        db.serialize_many(table, page), limit, offset, total_count
    )
