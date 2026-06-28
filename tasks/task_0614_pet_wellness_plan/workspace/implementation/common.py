"""Shared helpers: pagination parsing, body parsing, field validation,
and record bookkeeping (common system fields).

Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
List endpoints sort by created_at ASC (PRD §2.3).
"""
from flask import request

from errors import err, ERR_INVALID_REQUEST
from db import db, new_id, now_iso

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def parse_pagination():
    """Read limit/offset query params with PRD §2.3 defaults/bounds.

    Out-of-range / non-integer values are rejected with ERR_INVALID_REQUEST.
    """
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise err(ERR_INVALID_REQUEST, "limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list; return (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


def sort_by_created(rows):
    """Sort records by created_at ASC, tie-broken by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def get_json():
    """Parse the request JSON body; return {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def stamp_new(record):
    """Attach common system fields on create: id, created_at, updated_at,
    version, and an internal _seq insertion order (PRD §2.4)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation bookkeeping: refresh updated_at and bump version by one
    (PRD §2.4, §2.5)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def touch_no_version(record):
    """Mutation that refreshes updated_at WITHOUT bumping version. Used for the
    finalize-cancel pet cascade, where PRD §3.6 pins that the per-pet version
    rule does not fire."""
    record["updated_at"] = now_iso()


def public(record):
    """Strip internal-only keys (prefixed with '_') from a record copy."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def require_fields(data, names):
    """Ensure each required field is present and non-None."""
    for n in names:
        if n not in data or data[n] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {n}")


def require_int(data, name, *, minimum=None, maximum=None, required=True,
                default=None):
    """Validate an integer field with optional range. Booleans are rejected."""
    if name not in data or data[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = data[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"{name} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"{name} below minimum")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"{name} above maximum")
    return val


def require_number(data, name, *, gt=None, ge=None, le=None, required=True,
                   default=None):
    """Validate a numeric (int/float) field with optional bounds."""
    if name not in data or data[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = data[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"{name} must be a number")
    if gt is not None and not (val > gt):
        raise err(ERR_INVALID_REQUEST, f"{name} must be > {gt}")
    if ge is not None and not (val >= ge):
        raise err(ERR_INVALID_REQUEST, f"{name} must be >= {ge}")
    if le is not None and not (val <= le):
        raise err(ERR_INVALID_REQUEST, f"{name} must be <= {le}")
    return val


def require_str(data, name, *, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = data[name]
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"{name} must be a non-empty string")
    return val


def require_enum(data, name, choices, *, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = data[name]
    if val not in choices:
        raise err(ERR_INVALID_REQUEST, f"{name} must be one of {sorted(choices)}")
    return val


def require_bool(data, name, *, default=None):
    if name not in data or data[name] is None:
        return default
    val = data[name]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"{name} must be a boolean")
    return val
