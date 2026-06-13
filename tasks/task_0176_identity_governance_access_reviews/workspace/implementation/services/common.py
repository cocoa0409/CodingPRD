"""Shared helpers: serialization, pagination, OCC, field validation.

Serialization strips internal-only keys (those starting with "_") so the
response body never leaks the creation-order sequence.
"""
from datetime import datetime, timezone

import errors
from errors import err

# Pagination defaults (PRD §2.3, SCAFFOLD §1.0)
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def serialize(record):
    """Return a public copy of a record with internal keys removed."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


def parse_pagination(args):
    """Parse limit/offset query params. Raises ERR_VALIDATION when out of range
    (limit 1..100, offset >= 0). Missing -> defaults."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise err(errors.ERR_VALIDATION, "limit out of range 1..100")

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_VALIDATION, "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (creation order via _seq tiebreak) and slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], total


def require_fields(body, names):
    """Ensure every named field is present and not None. ERR_VALIDATION."""
    for name in names:
        if name not in body or body[name] is None:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)


def require_string(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_VALIDATION, "%s must be a non-empty string" % name)
    return val


def optional_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err(errors.ERR_VALIDATION, "%s must be a string" % name)
    return val


def require_int(body, name, minimum=None, maximum=None):
    """Required integer. Booleans are rejected (bool is a subclass of int)."""
    require_fields(body, [name])
    return _check_int(body[name], name, minimum, maximum)


def optional_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return _check_int(body[name], name, minimum, maximum)


def _check_int(val, name, minimum, maximum):
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_VALIDATION, "%s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err(errors.ERR_VALIDATION, "%s must be >= %s" % (name, minimum))
    if maximum is not None and val > maximum:
        raise err(errors.ERR_VALIDATION, "%s must be <= %s" % (name, maximum))
    return val


def require_bool(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, bool):
        raise err(errors.ERR_VALIDATION, "%s must be a boolean" % name)
    return val


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err(errors.ERR_VALIDATION, "%s must be a boolean" % name)
    return val


def require_array(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, list):
        raise err(errors.ERR_VALIDATION, "%s must be an array" % name)
    return val


def require_enum(body, name, allowed, default=None):
    """Optional enum with declared default; an out-of-set value -> ERR_INVALID_ENUM."""
    if name not in body or body[name] is None:
        if default is not None:
            return default
        raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)
    val = body[name]
    if val not in allowed:
        raise err(errors.ERR_INVALID_ENUM,
                  "%s must be one of %s" % (name, sorted(allowed)))
    return val


def filter_enum_param(args, name, allowed):
    """Validate a list-filter query param against an enum set. Out-of-set ->
    ERR_INVALID_ENUM. Missing -> None."""
    raw = args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise err(errors.ERR_INVALID_ENUM,
                  "%s must be one of %s" % (name, sorted(allowed)))
    return raw


def filter_bool_param(args, name):
    """Parse a boolean list-filter query param. Accepts true/false (any case).
    Out-of-range -> ERR_VALIDATION. Missing -> None."""
    raw = args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise err(errors.ERR_VALIDATION, "%s must be true or false" % name)


def parse_iso8601(value, name):
    """Parse an ISO 8601 UTC timestamp into an aware datetime. ERR_VALIDATION
    on a malformed value."""
    if not isinstance(value, str) or not value:
        raise err(errors.ERR_VALIDATION, "%s must be an ISO 8601 string" % name)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise err(errors.ERR_VALIDATION, "%s is not a valid ISO 8601 timestamp" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
