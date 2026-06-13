"""Auth header extraction and RBAC (PRD §2.1, §2.10; SCAFFOLD §1.7).

Headers: X-User-ID (acting principal), X-User-Role (capacity in which they act).
Known roles: ShopManager, ArtStaff, Customer, System (spelled exactly). A
request missing or malforming either header is rejected with
ERR_MISSING_OR_INVALID_USER_CONTEXT (400, priority 1). A syntactically valid
role not permitted for the operation -> ERR_FORBIDDEN_FOR_ROLE (403, priority 2).

Identity mapping (PRD §2.1): ShopManager / ArtStaff / System carry opaque
X-User-IDs the server never resolves to a stored record. A Customer's X-User-ID
is the id of the acting Customer entity; ownership checks compare a resource's
customer_id to X-User-ID.
"""
from functools import wraps

from flask import request, g

from errors import err

KNOWN_ROLES = {"ShopManager", "ArtStaff", "Customer", "System"}


def extract_identity():
    """Read auth headers into flask.g. Does not raise; checks run per-route."""
    g.user_id = request.headers.get("X-User-ID")
    g.user_role = request.headers.get("X-User-Role")


def require_auth():
    """Priority 1: both headers present and X-User-Role a known role."""
    uid = g.get("user_id")
    role = g.get("user_role")
    if not uid or not role:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT",
                  "Missing X-User-ID or X-User-Role header")
    if role not in KNOWN_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT", "Unknown role")


def require_role(*allowed):
    """Priority 2: the acting role must be permitted for this operation."""
    if g.get("user_role") not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Role not permitted for this operation")


def endpoint(*roles):
    """Decorator: run priority-1 auth then priority-2 RBAC before the handler."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            require_auth()
            require_role(*roles)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def is_customer():
    return g.get("user_role") == "Customer"


def require_owns_customer(customer_id):
    """Ownership check (PRD §2.1): an acting Customer may only touch resources
    whose customer_id equals their own X-User-ID. Opaque roles bypass."""
    if is_customer() and g.get("user_id") != customer_id:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Customer does not own this resource")
