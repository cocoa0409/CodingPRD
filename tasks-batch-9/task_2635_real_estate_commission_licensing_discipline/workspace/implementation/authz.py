"""Rung 1 (ERR_UNAUTHENTICATED) and rung 2 (ERR_FORBIDDEN_ROLE)."""
from flask import request

from errors import fail

ROLES = {
    "LicensingAnalyst", "TrustAuditor", "CommissionCounsel", "HearingPanelChair",
    "RecoveryFundTrustee", "Broker", "Salesperson", "Respondent", "ProviderAdmin",
    "Public",
}

ALL_STAFF = ["LicensingAnalyst", "TrustAuditor", "CommissionCounsel",
             "HearingPanelChair", "RecoveryFundTrustee"]


def identity():
    """Rung 1: both headers present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised role '%s'." % role)
    return str(user_id).strip(), role


def guard(allowed):
    """Rungs 1 then 2. Returns (user_id, role)."""
    user_id, role = identity()
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE",
             "Role %s may not perform this operation." % role)
    return user_id, role
