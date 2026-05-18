from flask import request
from errors import raise_error, ERR_VALIDATION


def get_pagination_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise_error(ERR_VALIDATION, "offset must be an integer")

    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    total_count = len(items)
    page = items[offset : offset + limit]
    has_more = (offset + limit) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return page, pagination
