"""Shared helpers: common-field stamping, pagination, body parsing/validation."""
from flask import request
from db import new_id, now_iso
from errors import err


def get_json_body():
    """Return parsed JSON body as dict, or {} for empty body. Parses regardless
    of the request Content-Type (force=True). Raises ERR_INVALID_REQUEST on a
    present-but-malformed body."""
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        raise err("ERR_INVALID_REQUEST", "Malformed or missing JSON body")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def stamp_create(record, with_version=True):
    """Set id, created_at, updated_at, version on a new record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    if with_version:
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on mutation."""
    record["updated_at"] = now_iso()
    if "version" in record:
        record["version"] = record["version"] + 1
    return record


def paginate():
    """Parse limit/offset query params per PRD §2.3. Returns (limit, offset).
    Raises ERR_INVALID_REQUEST for ill-typed/out-of-range values."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def page_slice(items, limit, offset):
    """Sort by created_at asc then id, then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {n}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))
