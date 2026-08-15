"""Request body shape validation helpers (gate: ERR_INVALID_REQUEST, 400)."""

from errors import ApiError, ERR_INVALID_REQUEST
import store


def body_or_empty(json_body):
    """POSTs with no declared input accept an absent/empty body."""
    return json_body if isinstance(json_body, dict) else {}


def require_fields(body: dict, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST,
                           f"Missing required field: {f}", 400)


def reject_version_fields(body: dict, allowed: tuple = ()):
    """PRD 2.7: only the two OCC endpoints accept version fields."""
    for key in ("expected_project_version", "expected_application_version"):
        if key in body and key not in allowed:
            raise ApiError(ERR_INVALID_REQUEST,
                           f"This endpoint does not accept {key}", 400)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST,
                       f"{field} must be a non-empty string", 400)
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST,
                       f"{field} must be one of {sorted(values)}", 400)
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an integer", 400)
    return v


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a number", 400)
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST,
                       f"{field} must be an ISO-8601 datetime string", 400)
    try:
        return store.parse_dt(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST,
                       f"{field} must be an ISO-8601 datetime string", 400)


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError(ERR_INVALID_REQUEST,
                       f"{field} must be an array of strings", 400)
    return v


def opt_category_amount_map(body, field):
    """Optional per-category numeric map (prior_use_basis / improvement_credits).

    Unknown category keys are tolerated (ignored by calculations); values must
    be non-negative numbers. Returns {} when the field is absent or null.
    """
    v = body.get(field)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an object", 400)
    out = {}
    for k, val in v.items():
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST,
                           f"{field}.{k} must be a number", 400)
        if val < 0:
            raise ApiError(ERR_INVALID_REQUEST,
                           f"{field}.{k} must be >= 0", 400)
        out[str(k)] = val
    return out


def reject_extra(body: dict, allowed_fields):
    """Silently ignore unknown fields (only OCC fields are policed)."""
    return body
