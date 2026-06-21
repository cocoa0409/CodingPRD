"""List endpoint helpers: filtering, sorting by created_at asc, pagination."""
from flask import request

from errors import err
from serializers import public


def _parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_LIMIT", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_LIMIT", "limit must be within [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_LIMIT", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION_LIMIT", "offset must be >= 0")
    return limit, offset


def paginate(records):
    """records: list of stored dicts. Returns (data_list, pagination_meta)."""
    limit, offset = _parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    data = [public(r) for r in window]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return data, pagination


def filter_by(records, **criteria):
    out = []
    for r in records:
        ok = True
        for key, val in criteria.items():
            if val is None:
                continue
            if r.get(key) != val:
                ok = False
                break
        if ok:
            out.append(r)
    return out
