"""Generic list pagination + default created_at-ASC ordering."""


def paginate(records, limit, offset, sort_key=None):
    """records: list of raw entity dicts. Returns (page_slice, total_count).
    Default sort: created_at ASC (using the raw _created_clock for stable order)."""
    if sort_key is None:
        ordered = sorted(records, key=lambda r: r.get("_created_clock"))
    else:
        ordered = sorted(records, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
