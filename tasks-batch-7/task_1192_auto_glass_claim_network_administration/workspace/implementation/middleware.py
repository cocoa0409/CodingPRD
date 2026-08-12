"""Auth context extraction, role checks, payload sanity, pagination."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
)

ROLE_POLICYHOLDER = "Policyholder"
ROLE_SHOP_OPERATOR = "ShopOperator"
ROLE_CLAIM_ADJUSTER = "ClaimAdjuster"
ROLE_NETWORK_AUDITOR = "NetworkAuditor"
ROLE_FRAUD_INVESTIGATOR = "FraudInvestigator"
ROLE_NETWORK_ADMIN = "NetworkAdmin"

ALL_ROLES = [
    ROLE_POLICYHOLDER,
    ROLE_SHOP_OPERATOR,
    ROLE_CLAIM_ADJUSTER,
    ROLE_NETWORK_AUDITOR,
    ROLE_FRAUD_INVESTIGATOR,
    ROLE_NETWORK_ADMIN,
]

AUDIT_READ_ROLES = [
    ROLE_CLAIM_ADJUSTER,
    ROLE_NETWORK_AUDITOR,
    ROLE_FRAUD_INVESTIGATOR,
    ROLE_NETWORK_ADMIN,
]


def get_context(allowed_roles):
    """Priority 1-2: presence of context headers, then endpoint role check."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not str(uid).strip() or not str(role).strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            f"Role {role} is not permitted for this endpoint",
        )
    return uid, role


def body_json(required=False):
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name):
    if not _present(data, name) or not isinstance(data[name], str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' is required and must be a string")
    return data[name]


def opt_str(data, name, default=None):
    if not _present(data, name):
        return default
    if not isinstance(data[name], str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be a string")
    return data[name]


def req_int(data, name):
    if not _present(data, name) or isinstance(data[name], bool) or not isinstance(data[name], int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' is required and must be an integer")
    return data[name]


def opt_int(data, name, default=None):
    if not _present(data, name):
        return default
    if isinstance(data[name], bool) or not isinstance(data[name], int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an integer")
    return data[name]


def req_bool(data, name):
    if not _present(data, name) or not isinstance(data[name], bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' is required and must be a boolean")
    return data[name]


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    if not isinstance(data[name], bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be a boolean")
    return data[name]


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"Field '{name}' must be one of {sorted(allowed)}",
        )
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"Field '{name}' must be one of {sorted(allowed)}",
        )
    return value


def req_str_list(data, name):
    if not _present(data, name) or not isinstance(data[name], list):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' is required and must be an array")
    for item in data[name]:
        if not isinstance(item, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must contain only strings")
    return data[name]


def pagination_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer")
        if limit < 1:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
