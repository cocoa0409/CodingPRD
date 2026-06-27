"""Shared helpers: serialization, pagination, body parsing/validation."""
from flask import request

import errors

# Pagination defaults (PRD §2.3 / SCAFFOLD §1.0).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def public_view(record):
    """Return a copy of a record with internal-only keys stripped."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def get_json_body():
    """Parse the JSON request body. Missing/empty body -> {}.

    A body that is present but not a JSON object is rejected as ERR_VALIDATION.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.validation("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.validation("Request body must be a JSON object.")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.validation(f"Missing required field: {name}.")
    return body[name]


def require_str(body, name):
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise errors.validation(f"Field {name} must be a non-empty string.")
    return value


def optional_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        raise errors.validation(f"Field {name} must be a string.")
    return value


def require_int(body, name, minimum=None, maximum=None):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.validation(f"Field {name} must be an integer.")
    if minimum is not None and value < minimum:
        raise errors.validation(f"Field {name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise errors.validation(f"Field {name} must be <= {maximum}.")
    return value


def optional_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.validation(f"Field {name} must be an integer.")
    if minimum is not None and value < minimum:
        raise errors.validation(f"Field {name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise errors.validation(f"Field {name} must be <= {maximum}.")
    return value


def require_bool(body, name):
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise errors.validation(f"Field {name} must be a boolean.")
    return value


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise errors.validation(f"Field {name} must be a boolean.")
    return value


def require_enum(body, name, allowed):
    value = require_field(body, name)
    if value not in allowed:
        raise errors.validation(
            f"Field {name} must be one of {sorted(allowed)}."
        )
    return value


def require_array(body, name):
    value = require_field(body, name)
    if not isinstance(value, list):
        raise errors.validation(f"Field {name} must be an array.")
    return value


def parse_pagination():
    """Read & validate limit/offset query params (PRD §2.3).

    limit defaults to 10, range [1, 100]. offset defaults to 0. An
    out-of-range or non-integer value is rejected with ERR_VALIDATION.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.validation(
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}."
            )

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer.")
        if offset < 0:
            raise errors.validation("offset must be >= 0.")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (with seq tiebreaker) then slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
