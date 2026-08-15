"""Authentication / authorization (PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = [
    "ProcurementLead",
    "SensoryGrader",
    "QALabAnalyst",
    "QAManager",
    "BlendMaster",
    "ProductionPlanner",
    "AccountManager",
    "CertificationOfficer",
    "PlatformAdmin",
]

ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present; role among the nine."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(
            ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return uid, role


def authorize(role, allowed):
    """Priority 2: caller role is listed for the endpoint."""
    if role not in allowed:
        raise_err(
            ERR_FORBIDDEN, "Role %s is not authorized for this endpoint" % role
        )
