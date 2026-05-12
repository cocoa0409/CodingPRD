"""Generic listing helper: filter, sort by created_at asc / _seq asc, paginate."""


def list_resource(table: dict, *, filters=None, projector=None,
                   limit: int = 10, offset: int = 0):
    """Apply optional filters dict (key -> value) — exact match. Project + paginate.

    Sort order: by _seq ascending (which corresponds to created_at ascending insertion).
    """
    rows = list(table.values())
    if filters:
        for k, v in filters.items():
            if v is None:
                continue
            rows = [r for r in rows if r.get(k) == v]
    rows.sort(key=lambda r: r.get("_seq", 0))
    total = len(rows)
    page = rows[offset: offset + limit]
    if projector:
        page = [projector(r) for r in page]
    return page, total
