"""Shared route helpers: pagination parsing and list slicing (PRD 2.3)."""
from flask import request

from errors import ERR_VALIDATION, raise_err
from response import success_list


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "limit must be between 1 and 100.")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer.")
        if offset < 0:
            raise_err(ERR_VALIDATION, "offset must be non-negative.")
    return limit, offset


def paginate(records, serializer):
    """Sort by creation ascending (insertion sequence) and slice."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)
