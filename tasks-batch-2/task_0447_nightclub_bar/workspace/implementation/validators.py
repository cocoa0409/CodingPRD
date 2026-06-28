"""Request-shape validation helpers (PRD §3.10 priority 5: ERR_INVALID_REQUEST).

Validates presence, type, enum membership, and non-negativity. Foreign-key
existence (ERR_FK_NOT_FOUND) and OCC (ERR_STALE_VENUE_VERSION) are handled in
the routes/domain layer at their own priorities.
"""
import errors


def get_body(req):
    """Return the JSON body as a dict, or raise ERR_INVALID_REQUEST."""
    if req.content_length in (None, 0):
        return {}
    try:
        data = req.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return body[field]


def as_string(value, field):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return value


def opt_string(body, field):
    if field not in body or body[field] is None:
        return None
    return as_string(body[field], field)


def as_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return value


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    return as_int(body[field], field, minimum=minimum)


def as_number(value, field, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    if lo is not None and value < lo:
        raise errors.invalid_request(f"Field {field} must be >= {lo}")
    if hi is not None and value > hi:
        raise errors.invalid_request(f"Field {field} must be <= {hi}")
    return value


def opt_number(body, field, default=None, lo=None, hi=None):
    if field not in body or body[field] is None:
        return default
    return as_number(body[field], field, lo=lo, hi=hi)


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise errors.invalid_request(
            f"Field {field} must be one of {sorted(allowed)}"
        )
    return value


def parse_iso_field(value, field):
    """Validate an ISO 8601 datetime string; return the raw string on success."""
    from clock import parse_iso
    if not isinstance(value, str):
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 string")
    try:
        parse_iso(value)
    except Exception:
        raise errors.invalid_request(f"Field {field} is not a valid ISO 8601 datetime")
    return value


def parse_date_field(value, field):
    """Validate a YYYY-MM-DD date string; return the raw string on success."""
    import datetime
    if not isinstance(value, str):
        raise errors.invalid_request(f"Field {field} must be a YYYY-MM-DD string")
    try:
        datetime.date.fromisoformat(value)
    except Exception:
        raise errors.invalid_request(f"Field {field} must be a valid YYYY-MM-DD date")
    return value


def paginate(req, items):
    """Apply limit/offset pagination (PRD §2.3). Returns (page, limit, offset, total)."""
    limit = req.args.get("limit")
    offset = req.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit_v < 1:
            limit_v = 1
        elif limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset_v < 0:
            offset_v = 0
    total = len(items)
    page = items[offset_v:offset_v + limit_v]
    return page, limit_v, offset_v, total
