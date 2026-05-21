from flask import request
from .errors import err


def parse_limit_offset():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise err("ERR_VALIDATION", "limit must be 1..100 and offset >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset : offset + limit]
    return window, total
