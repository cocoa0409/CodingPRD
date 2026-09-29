"""Shared list helper for every collection endpoint."""

from db import serialize_many
from response import ok_list
from validate import pagination


def paged(rows, strict=False):
    """Order is always created_at ASC (PRD §2.3); rows arrive pre-ordered."""
    limit, offset = pagination(strict=strict)
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list(serialize_many(window), limit, offset, total)
