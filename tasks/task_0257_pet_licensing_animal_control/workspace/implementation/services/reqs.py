"""Request body / query parsing helpers (PRD §2.3, §2.6, SCAFFOLD §1.4)."""
from flask import request

from errors import err


def body():
    """Return the JSON body as a dict (empty dict if none/invalid)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(data, fields):
    """All listed fields must be present and non-null (PRD §2.6 well-formedness)."""
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: {}".format(f))


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid value for {}.".format(field))


def parse_pagination():
    """limit (default 10, 1..100) and offset (default 0, >=0). Out of range ->
    ERR_VALIDATION (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit out of range (1..100).")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3) and slice. Returns (page, total)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
