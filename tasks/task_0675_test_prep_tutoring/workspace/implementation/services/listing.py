"""List helper: filter (already applied by caller), sort by created_at asc,
then paginate (PRD §2.3).

Sort is by _seq (insertion order) which is monotonic with created_at and breaks
ties deterministically by creation order.
"""


def sort_and_page(records, limit, offset):
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
