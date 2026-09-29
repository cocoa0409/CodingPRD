"""Shared route helpers."""

import response


def paginated(records, serializer):
    """Validate limit/offset, then serialize and window the record list."""
    limit, offset = response.pagination_params()
    return response.listing([serializer(rec) for rec in records], limit, offset)
