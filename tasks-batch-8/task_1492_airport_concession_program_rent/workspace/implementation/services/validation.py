"""Shared request-validation helpers used across route modules."""
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_ENUM

# Pagination defaults/bounds (scaffold response_envelope.pagination_defaults).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def check_enum(value, allowed, field='field'):
    if value not in allowed:
        raise ApiError(ERR_INVALID_ENUM, 400,
                       'Enum field carries an undeclared member: {0}'.format(field))
    return value


def paginate(items):
    """Offset/limit pagination per PRD section 2.3.

    Items must already be sorted by creation timestamp ascending.
    Returns (page, pagination_meta).
    """
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'limit must be an integer')
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, 'offset must be an integer')
    # limit is bounded below by 1 and above by 100; offset defaults to 0.
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page)) < total,
    }
    return page, meta
