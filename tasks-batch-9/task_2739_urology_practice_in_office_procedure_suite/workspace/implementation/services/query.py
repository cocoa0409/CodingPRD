"""Filtered, paginated collection reads (PRD sections 2.3 and 2.11)."""

import response
import validate
from db import store
from services import serialize


def collection(table_name, filters):
    limit, offset = validate.pagination()
    rows = store.all_rows(table_name)
    for field, value in filters.items():
        if value is None:
            continue
        rows = [row for row in rows if row.get(field) == value]
    total_count = len(rows)
    page = rows[offset : offset + limit]
    return response.array_response(serialize.dump_many(table_name, page), limit, offset, total_count)
