from flask import request
import errors

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.validation(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}.")

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation("offset must be an integer.")
        if offset < 0:
            raise errors.validation("offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list. Returns the page slice."""
    return items[offset:offset + limit]
