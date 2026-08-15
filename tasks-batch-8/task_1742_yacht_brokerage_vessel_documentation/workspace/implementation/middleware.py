"""Auth header extraction, role checking, and request validation helpers."""
from flask import request
from errors import err_unauthenticated, err_forbidden, err_invalid_request

ROLES = {"PlatformAdmin", "ListingAgent", "SellingAgent", "ClosingOfficer", "EscrowOfficer"}

ALL_ROLES = ["PlatformAdmin", "ListingAgent", "SellingAgent", "ClosingOfficer", "EscrowOfficer"]


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Priority 1: auth headers present and role valid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return Caller(user_id, role)


def require_roles(caller, allowed):
    """Priority 2: RBAC."""
    if caller.role not in allowed:
        raise err_forbidden()


def get_json_body():
    """Return the JSON body dict; {} when no body. Malformed -> 400."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def check_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return
    if body[field] not in allowed:
        raise err_invalid_request(f"Field {field} must be one of {sorted(allowed)}")


def check_int(body, field, required=True, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return
    v = body[field]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_request(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise err_invalid_request(f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise err_invalid_request(f"Field {field} must be <= {max_v}")


def check_str(body, field, required=True, non_empty=False):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return
    if not isinstance(body[field], str):
        raise err_invalid_request(f"Field {field} must be a string")
    if non_empty and body[field] == "":
        raise err_invalid_request(f"Field {field} must be non-empty")


def check_bool(body, field, required=False):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return
    if not isinstance(body[field], bool):
        raise err_invalid_request(f"Field {field} must be a boolean")


def check_number(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"Field {field} must be a number")


def parse_pagination():
    """limit/offset query params with defaults limit=10, offset=0; bounds 1..100 / 0.."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted by created_at ascending."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
