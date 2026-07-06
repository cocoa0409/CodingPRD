"""Shared list/filter/paginate logic (PRD §2.3).

Lists are sorted by created_at ascending; ties broken by insertion sequence so the
order is deterministic. Filters are applied before pagination; total_count is the
count after filtering but before the limit/offset window.
"""


def apply_filters(rows, filters):
    """filters: dict field -> expected value (already coerced). None skips."""
    out = rows
    for field, expected in filters.items():
        if expected is None:
            continue
        out = [r for r in out if r.get(field) == expected]
    return out


def sort_by_created(rows):
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total
