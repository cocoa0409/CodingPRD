"""Authentication / authorization helpers (PRD 2.1, validations p1-p2).

Every request carries X-User-ID and X-User-Role. Seven roles are recognized.
Driver and CustomerRep are entity-backed: their X-User-ID is the id of the
Driver / Customer entity they act as; the other five roles are opaque.
"""
from flask import request

from errors import err

FLEET_ADMIN = "FleetAdmin"
DISPATCHER = "Dispatcher"
TERMINAL_OPERATOR = "TerminalOperator"
WASH_OPERATOR = "WashOperator"
SAFETY_OFFICER = "SafetyOfficer"
DRIVER = "Driver"
CUSTOMER_REP = "CustomerRep"

ROLES = (
    FLEET_ADMIN, DISPATCHER, TERMINAL_OPERATOR, WASH_OPERATOR,
    SAFETY_OFFICER, DRIVER, CUSTOMER_REP,
)
ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: both headers present and the role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers are required and the role "
                  "must be one of the seven declared roles")
    return uid, role


def require_roles(role_list):
    """Priorities 1-2: header validity, then role membership on the endpoint."""
    uid, role = authenticate()
    if role not in role_list:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s is not authorized for this endpoint" % role)
    return uid, role


def require_driver_identity(uid, shipment):
    """Priority 2 identity match: a Driver caller acts on its own shipments."""
    if uid != shipment["driver_id"]:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Driver identity does not match the shipment's driver_id")


def require_customer_identity(uid, customer_id):
    """Priority 2 identity match: a CustomerRep caller acts on its own id."""
    if uid != customer_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "CustomerRep identity does not match the resource customer_id")
