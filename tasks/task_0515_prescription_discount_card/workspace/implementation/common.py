"""Shared route helpers: body parsing, pagination, typed field extraction, FK lookups."""
from flask import request
import errors

# Pagination defaults (SCAFFOLD §1.0 pagination_defaults)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def get_body():
    """Parse JSON body; tolerate empty body (returns {})."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def parse_pagination():
    """Return (limit, offset). Raises ERR_PAGINATION_INVALID on out-of-range."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.pagination_invalid("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.pagination_invalid("limit must be between 1 and 100.")

    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.pagination_invalid("offset must be an integer.")
        if offset < 0:
            raise errors.pagination_invalid("offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (PRD §2.3) then slice."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# ---------------------------------------------------------------------------
# Typed field extraction (raises ERR_INVALID_REQUEST on missing / wrong type)
# ---------------------------------------------------------------------------
def req_str(body, key, allow_empty=False):
    if key not in body:
        raise errors.invalid_request("Missing required field: %s" % key)
    val = body[key]
    if not isinstance(val, str) or isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a string." % key)
    if not allow_empty and val.strip() == "":
        raise errors.invalid_request("Field %s must not be empty." % key)
    return val


def opt_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str) or isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a string." % key)
    return val


def req_int(body, key):
    if key not in body:
        raise errors.invalid_request("Missing required field: %s" % key)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % key)
    return val


def req_number(body, key):
    if key not in body:
        raise errors.invalid_request("Missing required field: %s" % key)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field %s must be a number." % key)
    return val


def opt_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a boolean." % key)
    return val


def req_enum(body, key, allowed):
    val = req_str(body, key)
    if val not in allowed:
        raise errors.invalid_request("Field %s must be one of %s." % (key, sorted(allowed)))
    return val


def opt_list(body, key, default=None):
    if key not in body or body[key] is None:
        return list(default) if default is not None else []
    val = body[key]
    if not isinstance(val, list):
        raise errors.invalid_request("Field %s must be an array." % key)
    return val


def validate_state_code(value, key="state_code"):
    if not isinstance(value, str) or len(value) != 2 or not value.isalpha() or not value.isupper():
        raise errors.invalid_request("Field %s must be exactly 2 uppercase letters." % key)
    return value


# ---------------------------------------------------------------------------
# FK existence helpers (ERR_NOT_FOUND, priority 4)
# ---------------------------------------------------------------------------
def must_exist(table, resource_id, label="resource"):
    rec = table.get(resource_id)
    if rec is None:
        raise errors.not_found("%s not found." % label)
    return rec
