from flask import request

from errors import raise_error, ERR_PAGINATION_OUT_OF_RANGE


def parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    try:
        limit = int(limit_s) if limit_s is not None else 10
        offset = int(offset_s) if offset_s is not None else 0
    except Exception:
        raise_error(ERR_PAGINATION_OUT_OF_RANGE, "Invalid pagination parameters")
    if limit < 1 or limit > 100 or offset < 0:
        raise_error(ERR_PAGINATION_OUT_OF_RANGE, "Pagination out of range")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
