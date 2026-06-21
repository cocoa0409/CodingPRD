"""Shared helpers: common fields, pagination, body parsing/validation."""
from flask import request

from db import DB, new_id, now_iso
from errors import err, ERR_VALIDATION, ERR_INVALID_REQUEST


def stamp_create(record):
    """Attach common system fields (PRD §2.4): id, created_at, updated_at, version=1.

    Also records a monotonic sequence for deterministic creation-order sort.
    """
    record["id"] = new_id()
    ts = now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = DB.next_seq()
    return record


def touch(record):
    """A mutation (PRD §2.4): refresh updated_at and increment version by one."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def public_view(record):
    """Strip internal-only fields (those prefixed with '_')."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def get_json_body():
    """Parse JSON body, tolerating an empty body as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def parse_pagination():
    """PRD §2.3: limit default 10, min 1, max 100; offset default 0, min 0.

    A limit outside the permitted range is rejected with ERR_VALIDATION.
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION, "limit out of range")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(ERR_VALIDATION, "offset out of range")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by creation order (created_at asc, PRD §2.3) and slice."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [public_view(r) for r in window], total


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def as_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, "%s below minimum" % field)
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, "%s above maximum" % field)
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, "%s must be a string" % field)
    return val


def as_bool(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, "%s must be a boolean" % field)
    return val


def as_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    val = body[field]
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return val
