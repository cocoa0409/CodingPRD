"""Shared list/filter/pagination logic (PRD §2.3, §2.8)."""
from serialize import public
from response import list_response
from validation import parse_pagination


def paginated(collection, filters=None, serializer=public):
    """Filter by FK fields, sort by created_at ASC (tie-break by insertion seq),
    then page. filters maps field_name -> value (only applied when value is not None).
    """
    limit, offset = parse_pagination()
    rows = list(collection.values())
    if filters:
        for field, value in filters.items():
            if value is not None:
                rows = [r for r in rows if r.get(field) == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)
