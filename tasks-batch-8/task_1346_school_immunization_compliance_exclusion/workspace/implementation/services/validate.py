"""Request-body validation helpers.

Schema checks are deliberately LAST in the priority order (PRD §2.7 step 10),
so these helpers are invoked after business checks in each route handler.
"""

from db import parse_iso
from errors import ApiError, ERR_VALIDATION


def require_body(body):
    if body is None or not isinstance(body, dict):
        raise ApiError(ERR_VALIDATION, "Request body must be a JSON object.", 400)
    return body


def req_string(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_VALIDATION, f"Missing required field: {field}", 400)
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, f"Field {field} must be a string.", 400)
    return v


def opt_string(body, field, default=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, f"Field {field} must be a string.", 400)
    return v


def req_enum(body, field, allowed):
    v = req_string(body, field)
    if v not in allowed:
        raise ApiError(
            ERR_VALIDATION,
            f"Field {field} must be one of {sorted(allowed)}.",
            400,
        )
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_VALIDATION, f"Missing required field: {field}", 400)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, f"Field {field} must be an integer.", 400)
    if minimum is not None and v < minimum:
        raise ApiError(
            ERR_VALIDATION, f"Field {field} must be >= {minimum}.", 400
        )
    return v


def req_datetime(body, field):
    v = req_string(body, field)
    try:
        dt = parse_iso(v)
    except Exception:
        raise ApiError(
            ERR_VALIDATION, f"Field {field} must be an ISO 8601 datetime.", 400
        )
    return dt


def req_list_of_strings(body, field, allowed=None):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_VALIDATION, f"Missing required field: {field}", 400)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError(
            ERR_VALIDATION, f"Field {field} must be a list of strings.", 400
        )
    if allowed is not None:
        for x in v:
            if x not in allowed:
                raise ApiError(
                    ERR_VALIDATION,
                    f"Field {field} contains an invalid value: {x}",
                    400,
                )
    return v


def parse_pagination(args):
    """Parse limit/offset query params per PRD §2.3. Defaults: limit=10, offset=0.
    Min limit 1, max limit 100."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "limit must be an integer.", 400)
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "offset must be an integer.", 400)
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
