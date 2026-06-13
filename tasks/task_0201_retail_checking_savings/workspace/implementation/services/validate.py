"""Request body validation helpers (PRD §2.9)."""
from flask import request
import errors
from errors import ApiError


def get_body():
    """Return the JSON body as a dict (empty dict if no body)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Body must be a JSON object")
    return body


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422, f"Missing required field: {f}")


def require_enum(body, field, domain):
    val = body.get(field)
    if val not in domain:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       f"Field {field} must be one of {sorted(domain)}")
    return val


def require_positive_int_amount(value):
    """amount_cents must be a strictly positive integer (PRD §2.9 -> ERR_INVALID_AMOUNT)."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ApiError(errors.ERR_INVALID_AMOUNT, 422,
                       "amount_cents must be a strictly positive integer")
    return value


def require_nonneg_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ApiError(errors.ERR_INVALID_AMOUNT, 422, f"{field} must be >= 0")
    return value
