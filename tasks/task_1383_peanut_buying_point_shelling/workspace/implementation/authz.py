"""Authentication / authorization helpers (PRD 2.1, validations priorities 1,3,5)."""
from flask import request

from errors import unauthenticated, forbidden, ownership_forbidden

ADMIN = "BuyingPointAdmin"
GROWER = "Grower"
INSPECTOR = "GradingInspector"
LABTECH = "LabTechnician"
CLERK = "SettlementClerk"
SHELLER = "ShellerRep"

ROLES = (ADMIN, GROWER, INSPECTOR, LABTECH, CLERK, SHELLER)


def authenticate():
    """Priority 1: X-User-ID / X-User-Role present and role is declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return uid, role


def require_roles(role_list):
    """Priority 3: role membership for the endpoint (call after schema checks)."""
    uid, role = authenticate()
    if role not in role_list:
        raise forbidden()
    return uid, role


def check_grower_ownership(uid, role, grower_id):
    """Priority 5: a Grower acts only on its own resources."""
    if role == GROWER and uid != grower_id:
        raise ownership_forbidden()


def check_sheller_ownership(uid, role, contract):
    """Priority 5: a ShellerRep acts only on contracts with sheller_ref == X-User-ID."""
    if role == SHELLER and contract["sheller_ref"] != uid:
        raise ownership_forbidden()
