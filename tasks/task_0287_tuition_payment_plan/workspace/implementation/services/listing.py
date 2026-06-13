"""List helper: filter, sort by created_at ascending, paginate (PRD §2.3)."""
from services.validate import pagination_params
from response import list_success


def paginate_and_render(records, view_fn):
    """records: pre-filtered list of stored dicts. Sort by created_at asc
    (PRD §2.3), then by id as a stable tiebreaker, paginate, and render.
    """
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    items = [view_fn(r) for r in page]
    return list_success(items, limit, offset, total)
