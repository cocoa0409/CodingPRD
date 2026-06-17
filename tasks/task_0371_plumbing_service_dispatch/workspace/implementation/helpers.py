"""Shared parsing / validation / pagination helpers."""
from flask import request

from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
import db

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Parse the JSON body. Missing/empty body is treated as {}.

    A body that is present but malformed raises ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


def as_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    # bool is a subclass of int — reject it as a non-integer here.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s" % (name, maximum))
    return v


def as_number(body, name, required=True, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s" % (name, maximum))
    return v


def as_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST,
                  "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3. Out-of-range -> 400."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err(ERR_INVALID_REQUEST,
                      "limit must be between %d and %d" %
                      (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def sort_by_created(records):
    """Sort by created_at ascending, tie-break by internal sequence (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


def find_or_404(collection, rid, label="resource"):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "%s not found: %s" % (label, rid))
    return rec
