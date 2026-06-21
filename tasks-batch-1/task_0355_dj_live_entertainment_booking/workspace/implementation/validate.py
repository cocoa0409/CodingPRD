"""Generic request well-formedness helpers (priority 6: ERR_INVALID_REQUEST)
and pagination parsing (ERR_VALIDATION_LIMIT)."""
from flask import request

from errors import invalid_request, validation_limit


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none)."""
    if request.content_length in (0, None) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise invalid_request("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise invalid_request(f"Missing required field: {field}")
    return body[field]


def require_nonempty_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val.strip() == "":
        raise invalid_request(f"{field} must be a non-empty string")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise invalid_request(f"{field} must be a string")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise invalid_request(f"{field} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise invalid_request(f"{field} must be one of {sorted(allowed)}")
    return val


def _as_int(val, field):
    # bool is a subclass of int; reject explicit booleans.
    if isinstance(val, bool) or not isinstance(val, int):
        raise invalid_request(f"{field} must be an integer")
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = _as_int(require(body, field), field)
    _check_bounds(val, field, minimum, maximum)
    return val


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    val = _as_int(body[field], field)
    _check_bounds(val, field, minimum, maximum)
    return val


def _check_bounds(val, field, minimum, maximum):
    if minimum is not None and val < minimum:
        raise invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise invalid_request(f"{field} must be <= {maximum}")


def require_str_field(body, field):
    """A field that must be present and a string (FK ids). Emptiness handled by
    existence check elsewhere; but enforce string type / presence here."""
    val = require(body, field)
    if not isinstance(val, str) or val.strip() == "":
        raise invalid_request(f"{field} must be a non-empty string")
    return val


def parse_pagination():
    """Parse limit/offset query params. Bounds: limit in [1,100], offset >= 0.

    On violation raise ERR_VALIDATION_LIMIT (422). Non-integer also rejected
    with the same error (only check that fires on list GETs).
    """
    args = request.args

    def parse_one(name, default):
        raw = args.get(name)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (ValueError, TypeError):
            raise validation_limit(f"{name} must be an integer")

    limit = parse_one("limit", 10)
    offset = parse_one("offset", 0)
    if limit < 1 or limit > 100:
        raise validation_limit("limit must be within [1, 100]")
    if offset < 0:
        raise validation_limit("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (tie-break by insertion sequence), then
    window. Returns (page_items, total_count)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
