"""Request-body and pagination validation helpers."""
from flask import request

from errors import err

VEHICLE_SIZES = {"SEDAN", "SUV", "TRUCK", "XL"}
TIERS = {"WASH", "FULL", "CERAMIC"}
ADDON_CODES = {"ENGINE_BAY", "PET_HAIR", "HEADLIGHT"}
LOCATION_MODES = {"SHOP", "MOBILE"}


def get_body():
    """Parse the JSON request body, tolerating an absent body as {}.

    A malformed (non-JSON) body is an ERR_INVALID_REQUEST. A JSON value that is
    not an object is likewise rejected."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return body


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def require_int(body, field, minimum=None, gt=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    if gt is not None and v <= gt:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be > {gt}")
    return v


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be a boolean")
    return v


def optional_int(body, field, default, minimum=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    return v


def parse_pagination():
    """Return (limit, offset). limit default 10 (min 1, max 100), offset default 0
    (min 0). Out-of-range -> ERR_VALIDATION (PRD §2.3)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit out of range")
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset out of range")
    return limit, offset


def paginate(rows, limit, offset):
    """rows: list already sorted by creation order. Returns the page slice."""
    return rows[offset:offset + limit]
