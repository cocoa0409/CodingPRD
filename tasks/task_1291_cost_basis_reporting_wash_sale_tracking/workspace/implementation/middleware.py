"""Auth header extraction, role checking, pagination, body validation."""

from flask import request

from errors import (
    ApiError,
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
)

ROLES = {"FirmAdmin", "TaxOps", "CustomerService", "Customer", "Auditor"}

# Entity names that Customer-role callers may see only for their own customer_id.
CUSTOMER_SCOPED_RESOURCES = {
    "Customer", "Account", "TaxLot", "Disposition", "TaxForm1099B",
    "BasisChangeRequest", "CorporateAction", "Security", "WashSaleEvent",
    "TransferStatement", "BrokerageFirm",
}


def get_actor():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID header is missing or malformed")
    if not role or not isinstance(role, str) or role.strip() not in ROLES:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-Role header is missing or malformed")
    return user_id.strip(), role.strip()


def require_roles(allowed_roles):
    """Ensure the caller's role is admitted on this endpoint."""
    user_id, role = get_actor()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_FOR_ROLE,
                  f"Role {role} is not permitted for this endpoint")
    return user_id, role


def get_json_body(required=True):
    """Parse JSON body; raise ERR_INVALID_REQUEST on malformed."""
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if body is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Request body is required")
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def parse_pagination(args):
    """Read limit/offset with defaults from the envelope spec."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def customer_owns(actor_user_id, actor_role, customer_id):
    """Customer-role callers may only touch their own customer_id."""
    if actor_role != "Customer":
        return True
    return actor_user_id == customer_id
