"""Body-shape & pagination validation helpers (ERR_INVALID_REQUEST, PRD §2.3, §2.10)."""
from flask import request

import errors


def get_json_body():
    """Parse the JSON body, defaulting to {} when empty. Raises ERR_INVALID_REQUEST
    on malformed JSON."""
    if request.method in ("GET", "DELETE"):
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request("Missing required field: %s" % f)


def require_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return None
    val = body[field]
    if val not in allowed:
        raise errors.invalid_request("Invalid value for %s" % field)
    return val


def require_int(body, field, required=True, minimum=None, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("%s must be >= %s" % (field, minimum))
    return val


def require_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("%s must be a non-empty string" % field)
    return val


def optional_str(body, field):
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request("%s must be a string" % field)
    return val


def parse_pagination():
    """Return (limit, offset). Validates per PRD §2.3:
    limit defaults 10, must be int in [1, 100]; offset defaults 0, must be int >= 0.
    Invalid → ERR_INVALID_REQUEST (400)."""
    args = request.args

    limit = 10
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")

    offset = 0
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
