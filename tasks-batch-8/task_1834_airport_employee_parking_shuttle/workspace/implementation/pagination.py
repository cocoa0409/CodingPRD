"""Pagination parameter parsing per scaffold response_envelope."""
from flask import request

from errors import raise_error


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_error("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset
