"""Auth headers (PRD 2.1), request-shape helpers (band 7) and enum sets."""

from flask import request

from errors import ApiError
from util import parse_date, parse_datetime

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
SELLER_OPS = "SellerOps"
BUYER = "Buyer"
MARKETPLACE_OPS = "MarketplaceOps"
TRUST_SAFETY = "TrustSafety"

ALL_ROLES = (PLATFORM_ADMIN, SELLER_OPS, BUYER, MARKETPLACE_OPS, TRUST_SAFETY)

CATEGORY_CODES = ("APPAREL", "ELECTRONICS", "HOME_GOODS", "TOYS")
CONDITION_GRADES = ("NEW_OVERSTOCK", "CUSTOMER_RETURNS", "SALVAGE")
DECLARED_CONDITIONS = ("NEW", "LIKE_NEW", "USED_GOOD", "DAMAGED", "SALVAGE")
LISTING_FORMATS = ("AUCTION", "FIXED_PRICE", "NEGOTIATED")
RESALE_CHANNELS = (
    "MARKETPLACE_RESALE", "EXPORT_ONLY", "DISCOUNT_RETAIL", "SCRAP_ONLY",
)
CLAIM_TYPES = ("UNIT_SHORTAGE", "CONDITION_MISGRADE", "MISSING_SKU")
GROUP_BY_VALUES = ("NONE", "CATEGORY", "CHANNEL")


def authenticate(allowed_roles):
    """Band 1 then band 2: identity headers, then role admission."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(name, why):
    return ApiError("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def present(payload, name):
    return name in payload and payload.get(name) is not None


def req_str(payload, name):
    value = payload.get(name)
    if value is None:
        raise _bad(name, "is required.")
    if not isinstance(value, str) or not value.strip():
        raise _bad(name, "must be a non-empty string.")
    return value


def opt_str(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload.get(name)
    if not isinstance(value, str):
        raise _bad(name, "must be a string.")
    return value


def req_int(payload, name, minimum=None, maximum=None):
    value = payload.get(name)
    if value is None:
        raise _bad(name, "is required.")
    return _as_int(name, value, minimum, maximum)


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    return _as_int(name, payload.get(name), minimum, maximum)


def _as_int(name, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(name, "must be an integer.")
    if minimum is not None and value < minimum:
        raise _bad(name, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        raise _bad(name, "must be at most %d." % maximum)
    return value


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        raise _bad(name, "must be one of %s." % ", ".join(allowed))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    value = payload.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise _bad(name, "must be one of %s." % ", ".join(allowed))
    return value


def req_bool(payload, name):
    value = payload.get(name)
    if value is None:
        raise _bad(name, "is required.")
    if not isinstance(value, bool):
        raise _bad(name, "must be a boolean.")
    return value


def opt_bool(payload, name, default=False):
    if not present(payload, name):
        return default
    value = payload.get(name)
    if not isinstance(value, bool):
        raise _bad(name, "must be a boolean.")
    return value


def req_datetime(payload, name):
    raw = payload.get(name)
    if raw is None:
        raise _bad(name, "is required.")
    parsed = parse_datetime(raw)
    if parsed is None:
        raise _bad(name, "must be an ISO 8601 UTC timestamp.")
    return parsed


def opt_datetime(payload, name, default=None):
    if not present(payload, name):
        return default
    parsed = parse_datetime(payload.get(name))
    if parsed is None:
        raise _bad(name, "must be an ISO 8601 UTC timestamp.")
    return parsed


def opt_date(payload, name, default=None):
    if not present(payload, name):
        return default
    parsed = parse_date(payload.get(name))
    if parsed is None:
        raise _bad(name, "must be a YYYY-MM-DD date.")
    return parsed


def opt_str_list(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload.get(name)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _bad(name, "must be an array of strings.")
    return list(value)


def req_str_list(payload, name, non_empty=True):
    value = payload.get(name)
    if value is None:
        raise _bad(name, "is required.")
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise _bad(name, "must be an array of strings.")
    if non_empty and not value:
        raise _bad(name, "must not be empty.")
    return list(value)
