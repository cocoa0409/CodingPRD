"""Shared helpers: serialization, pagination, body parsing, field validation."""
from flask import request

import errors

# Field order is not significant for JSON; we just hide internal bookkeeping.
_HIDDEN = {"_seq"}


def serialize(rec):
    """Return a copy of the record without internal bookkeeping fields."""
    return {k: v for k, v in rec.items() if k not in _HIDDEN}


def get_json_body():
    """Parse the request JSON body. Missing/invalid JSON -> empty dict.

    A body that is present but not a JSON object is treated as malformed.
    """
    if request.method in ("POST", "PUT", "PATCH"):
        raw = request.get_data(cache=True, as_text=True)
        if raw is None or raw.strip() == "":
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object")
        return data
    return {}


def paginate(items):
    """Apply limit/offset pagination per PRD §2.3.

    limit defaults 10, min 1, max 100. offset defaults 0, min 0. Returns
    (page_items, limit, offset, total_count). Invalid pagination params ->
    ERR_INVALID_REQUEST.
    """
    total_count = len(items)

    limit = _parse_int_param("limit", default=10, minimum=1, maximum=100)
    offset = _parse_int_param("offset", default=0, minimum=0, maximum=None)

    page = items[offset:offset + limit]
    return page, limit, offset, total_count


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Invalid {name} parameter")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"{name} below minimum")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"{name} above maximum")
    return val


def sort_by_created(items):
    """Sort by created_at ascending; _seq breaks ties (PRD §2.3)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# --- body field validators ----------------------------------------------------

def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def require_string(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, str) or val.strip() == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string")
    return val


def require_int(body, name):
    require_fields(body, [name])
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    return val


def require_positive_int(body, name):
    """Integer that must be > 0 (no negative/zero where positive required)."""
    val = require_int(body, name)
    if val <= 0:
        raise errors.invalid_request(f"Field {name} must be a positive integer")
    return val


def require_nonneg_int(body, name):
    val = require_int(body, name)
    if val < 0:
        raise errors.invalid_request(f"Field {name} must not be negative")
    return val


def optional_nonneg_int(body, name, default=0):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    if val < 0:
        raise errors.invalid_request(f"Field {name} must not be negative")
    return val


def require_number(body, name):
    require_fields(body, [name])
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number")
    return val


def require_enum(body, name, members):
    val = require_string(body, name)
    if val not in members:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(members)}")
    return val


def optional_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return val
