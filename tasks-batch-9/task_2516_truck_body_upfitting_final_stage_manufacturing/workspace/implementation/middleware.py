"""Authentication, authorization, customer scoping and segregation of duties.

Precedence (PRD section 2.6): authentication (1) -> authorization (2) ->
customer scope (3) -> segregation of duties (4).  Every one of these sits above
request-shape validation, existence, concurrency and state checks.
"""

from flask import g, request

import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_PLANT_ADMIN = "PlantAdmin"
ROLE_PRODUCTION_SCHEDULER = "ProductionScheduler"
ROLE_UPFIT_ENGINEER = "UpfitEngineer"
ROLE_INSTALL_TECHNICIAN = "InstallTechnician"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"
ROLE_CUSTOMER = "Customer"

STAFF_ROLES = (
    ROLE_PLANT_ADMIN,
    ROLE_PRODUCTION_SCHEDULER,
    ROLE_UPFIT_ENGINEER,
    ROLE_INSTALL_TECHNICIAN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_WARRANTY_ADMINISTRATOR,
)
ALL_ROLES = STAFF_ROLES + (ROLE_CUSTOMER,)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == ROLE_CUSTOMER


def authenticate():
    """Both headers must be present, non-empty, and the role must be one of the
    seven declared values; otherwise ERR_UNAUTHENTICATED (401)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "Missing %s header." % USER_ID_HEADER)
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "Missing %s header." % USER_ROLE_HEADER)
    user_id = str(user_id).strip()
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unrecognised role '%s'." % role)
    caller = Caller(user_id, role)
    g.caller = caller
    return caller


def require(*allowed_roles):
    """Authenticate, then authorize against the endpoint's role list."""
    caller = authenticate()
    if caller.role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role '%s' may not perform this operation." % caller.role,
        )
    return caller


def scope_violation(message=None):
    return ApiError("ERR_CUSTOMER_SCOPE_VIOLATION", message)


def enforce_order_scope(caller, order):
    """A Customer caller may only reach rows hanging off an order whose
    customer_id equals its own X-User-ID."""
    if order is None or not caller.is_customer:
        return
    if order.get("customer_id") != caller.user_id:
        raise scope_violation("This upfit order belongs to another customer account.")


def enforce_customer_scope(caller, customer_id):
    if not caller.is_customer:
        return
    if customer_id != caller.user_id:
        raise scope_violation("Customer callers may only read their own account record.")


def visible_orders(caller):
    """Row set a caller may see: everything for staff, own orders for a Customer."""
    rows = list(db.upfit_orders.values())
    if caller.is_customer:
        rows = [o for o in rows if o.get("customer_id") == caller.user_id]
    return rows


def scope_filter_by_order(caller, rows):
    """Restrict a child collection to the caller's own orders."""
    if not caller.is_customer:
        return rows
    return [
        r
        for r in rows
        if (db.upfit_orders.get(r.get("upfit_order_id")) or {}).get("customer_id") == caller.user_id
    ]


def enforce_segregation(caller, other_user_id, message):
    """Segregation of duties sits above every existence and state check for the
    operations that declare it (PRD section 2.6 step 4)."""
    if other_user_id is not None and caller.user_id == other_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", message)
