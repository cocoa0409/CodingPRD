"""Shared list-endpoint plumbing."""

import response
import validate


def paged(rows, filter_spec, serializer):
    """Ladder step 7 first, then filters, then created_at ASC ordering."""
    limit, offset = validate.pagination()
    kept = [row for row in rows if validate.matches_filters(row, filter_spec)]
    kept = validate.sorted_rows(kept)
    total = len(kept)
    window = kept[offset : offset + limit]
    return response.collection(window, serializer, limit, offset, total)
