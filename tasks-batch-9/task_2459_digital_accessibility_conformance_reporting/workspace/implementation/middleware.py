"""Authentication / authorization (PRD 2.1, validation steps 1-3)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "AccessibilityLead",
    "AccessibilityTester",
    "ConformanceReviewer",
    "ProductOwner",
    "CustomerLiaison",
)

ALL_ROLES = list(ROLES)


def endpoint(roles):
    """Step 1: headers present + role recognised.  Step 2: role authorized."""
    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED",
                               "Authentication headers are missing or invalid")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED",
                               "Role %s may not perform this operation" % role)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_product_ownership(product_id):
    """Step 3: a ProductOwner's X-User-ID is the Product.id it acts for."""
    if g.role == "ProductOwner" and g.user_id != product_id:
        raise ApiError(
            "ERR_PRODUCT_OWNERSHIP_MISMATCH",
            "ProductOwner %s does not own product %s" % (g.user_id, product_id))
