"""Authentication, role validity, endpoint permission, identity resolution,
role/identity agreement and customer scope: ladder priorities 1 to 6."""
from flask import request

import core
from core import S
from errors import fail

TECH_ROLES = {
    "ResinTechnician": "RESIN_TECH",
    "MoldingOperator": "MOLDING_OPERATOR",
    "AssemblyTechnician": "ASSEMBLY_TECH",
    "QualityInspector": "QUALITY_INSPECTOR",
}
OPAQUE_ROLES = ("PlantAdmin", "LogisticsPlanner", "WarrantyAgent")
CUSTOMER_ROLE = "Customer"
ALL_ROLES = tuple(OPAQUE_ROLES) + tuple(TECH_ROLES.keys()) + (CUSTOMER_ROLE,)

READ_ALL_ROLES = (
    "PlantAdmin", "ResinTechnician", "MoldingOperator", "AssemblyTechnician",
    "QualityInspector", "LogisticsPlanner", "WarrantyAgent",
)


class Ctx(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.technician = None
        self.customer = None


def authenticate(allowed_roles):
    """Priorities 1-5.  Returns the request context."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role are required.")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ALL_ROLES:
        fail("ERR_INVALID_ROLE", "Unknown role '%s'." % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role '%s' may not call this endpoint." % role)
    ctx = Ctx(user_id, role)
    if role in TECH_ROLES:
        tech = S.technicians.get(user_id)
        if tech is None:
            fail("ERR_IDENTITY_NOT_FOUND", "X-User-ID does not resolve to a technician.")
        ctx.technician = tech
        if tech["role_code"] != TECH_ROLES[role]:
            fail(
                "ERR_ROLE_IDENTITY_MISMATCH",
                "Technician role_code %s cannot assert %s." % (tech["role_code"], role),
            )
    elif role == CUSTOMER_ROLE:
        cust = S.customers.get(user_id)
        if cust is None:
            fail("ERR_IDENTITY_NOT_FOUND", "X-User-ID does not resolve to a customer.")
        ctx.customer = cust
    return ctx


def require_active(tech):
    if tech is not None and tech["status"] != "ACTIVE":
        fail("ERR_TECHNICIAN_SUSPENDED", "Technician is suspended.")


def require_cert(tech, needed):
    held = tech.get("certifications") or []
    for cert in needed:
        if cert not in held:
            fail("ERR_TECHNICIAN_NOT_CERTIFIED", "Technician lacks %s." % cert)


# --------------------------------------------------------------------------
# Customer scope (priority 6).
# --------------------------------------------------------------------------
def scope_claim(ctx, claim):
    if ctx.role == CUSTOMER_ROLE and claim is not None:
        if claim["customer_id"] != ctx.user_id:
            fail("ERR_CUSTOMER_SCOPE_VIOLATION", "Claim belongs to another customer.")


def scope_customer_row(ctx, customer):
    if ctx.role == CUSTOMER_ROLE and customer is not None:
        if customer["id"] != ctx.user_id:
            fail("ERR_CUSTOMER_SCOPE_VIOLATION", "Customer record belongs to another customer.")


def _customer_owns_unit(ctx, unit):
    for claim in S.warranty_claims.values():
        if claim["finished_unit_id"] == unit["id"] and claim["customer_id"] == ctx.user_id:
            return True
    for line in S.shipment_lines.values():
        if line["finished_unit_id"] != unit["id"]:
            continue
        ship = S.shipments.get(line["shipment_id"])
        if ship and ship.get("customer_id") == ctx.user_id:
            return True
    return False


def scope_unit(ctx, unit):
    if ctx.role == CUSTOMER_ROLE and unit is not None:
        if not _customer_owns_unit(ctx, unit):
            fail("ERR_CUSTOMER_SCOPE_VIOLATION", "Hull belongs to another customer.")


def scope_shipment(ctx, shipment):
    if ctx.role != CUSTOMER_ROLE or shipment is None:
        return
    if shipment.get("customer_id") == ctx.user_id:
        return
    for line in S.shipment_lines.values():
        if line["shipment_id"] != shipment["id"]:
            continue
        unit = S.finished_units.get(line["finished_unit_id"])
        if unit and _customer_owns_unit(ctx, unit):
            return
    fail("ERR_CUSTOMER_SCOPE_VIOLATION", "Trailer belongs to another customer.")


def scope_claim_list(ctx, claims):
    if ctx.role == CUSTOMER_ROLE:
        return [c for c in claims if c["customer_id"] == ctx.user_id]
    return claims
