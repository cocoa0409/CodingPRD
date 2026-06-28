"""Shared helpers: body parsing, pagination, sorting, FK existence checks.

Pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults):
  limit default 10, min 1, max 100; offset default 0, may not be negative.
Out-of-range -> ERR_INVALID_REQUEST.
List default sort: created_at ascending (PRD §2.3), ties by creation sequence.
"""
from flask import request

import errors


def get_json_body():
    """Parse JSON body; reject malformed bodies with ERR_INVALID_REQUEST."""
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Malformed JSON body.")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object.")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def require_non_empty_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val.strip() == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string.")
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field {field} must be <= {maximum}.")
    return val


def require_number(body, field, minimum=None, maximum=None, max_exclusive=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Field {field} must be <= {maximum}.")
    if max_exclusive is not None and val >= max_exclusive:
        raise errors.invalid_request(f"Field {field} must be < {max_exclusive}.")
    return val


def require_bool(body, field):
    val = body.get(field)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean.")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}.")
    return val


def optional_enum(value, allowed, field="value"):
    """Validate a query-param enum value if present; unknown -> ERR_INVALID_REQUEST."""
    if value is None:
        return None
    if value not in allowed:
        raise errors.invalid_request(f"Invalid {field}: {value}")
    return value


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset may not be negative.")
    return limit, offset


def sort_created_asc(records):
    # created_at ascending; deterministic tiebreak on the monotonic _seq.
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


def serialize(entity):
    """Strip internal-only fields (leading underscore) from API output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(entities):
    return [serialize(e) for e in entities]


def str_arg(name):
    return request.args.get(name)


def bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise errors.invalid_request(f"{name} must be a boolean.")
