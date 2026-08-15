"""Auth header extraction, role checking, ownership helpers (PRD §2.1)."""
import functools

from flask import request, g

from errors import err_unauthenticated, err_unauthorized, err_invalid_request

DECLARED_ROLES = {
    "Anonymous", "PlatformAdmin", "CatalogManager", "Buyer",
    "AccountApprover", "WarehouseOps", "CustomerService",
}

# Roles whose X-User-ID is the id of the acting Account (entity-backed).
ENTITY_BACKED_ROLES = {"Buyer", "AccountApprover"}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in DECLARED_ROLES:
        raise err_unauthenticated()
    g.user_id = uid
    g.role = role


def require_roles(*roles):
    """Decorator: authenticate, then enforce endpoint role membership."""
    def wrapper(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            authenticate()
            if g.role == "Anonymous" or g.role not in roles:
                raise err_unauthorized()
            return fn(*args, **kwargs)
        return inner
    return wrapper


def is_entity_backed():
    return g.role in ENTITY_BACKED_ROLES


def check_account_ownership(account_id):
    """For Buyer/AccountApprover, X-User-ID must equal the owning account id."""
    if g.role in ENTITY_BACKED_ROLES and g.user_id != account_id:
        raise err_unauthorized()


def scoped_account_id():
    """Return the account id an entity-backed caller is restricted to, else None."""
    if g.role in ENTITY_BACKED_ROLES:
        return g.user_id
    return None


def get_json_body(required=False):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise err_invalid_request("Request body must be a JSON object.")
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object.")
    return body


def require_field(body, field):
    if field not in body or body[field] is None:
        raise err_invalid_request(f"Missing required field: {field}.")
    return body[field]


def require_str(body, field):
    v = require_field(body, field)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"Field '{field}' must be a non-empty string.")
    return v


def optional_str(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise err_invalid_request(f"Field '{field}' must be a string.")
    return v


def require_int(body, field):
    v = require_field(body, field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_request(f"Field '{field}' must be an integer.")
    return v


def optional_int(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_request(f"Field '{field}' must be an integer.")
    return v


def optional_bool(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, bool):
        raise err_invalid_request(f"Field '{field}' must be a boolean.")
    return v


def optional_number(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise err_invalid_request(f"Field '{field}' must be a number.")
    return v
