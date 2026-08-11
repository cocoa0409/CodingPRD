"""Auth middleware per scaffold validations priorities 1-3 / PRD §2.1.

Headers: X-User-ID and X-User-Role. Roles: Customer, FrontDesk, Technician,
Manager. Missing/invalid headers -> ERR_UNAUTHENTICATED; role not in the
endpoint's list -> ERR_UNAUTHORIZED; Customer touching another customer's
resource -> ERR_FORBIDDEN_OWNERSHIP.
"""

from flask import g, request

from errors import err

ROLES = ("Customer", "FrontDesk", "Technician", "Manager")


def auth(*roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role / X-User-ID headers")
    if role not in roles:
        raise err("ERR_UNAUTHORIZED", "Role %s is not permitted for this endpoint" % role)
    g.user_role = role
    g.user_id = uid


def check_own(customer_id):
    """Customer role may only touch resources whose customer chain == X-User-ID."""
    if g.user_role == "Customer" and g.user_id != customer_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Customers may only access their own resources")
