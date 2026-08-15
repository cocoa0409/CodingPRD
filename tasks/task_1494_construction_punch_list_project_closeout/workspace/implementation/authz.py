"""Authentication / authorization helpers (PRD 2.1, validation priorities 1-4)."""
from flask import request

from errors import unauthenticated, forbidden, not_responsible_party

GCPM = "GCProjectManager"
GCINSP = "GCInspector"
OWNER = "OwnerRep"
SUBREP = "SubcontractorRep"

ROLES = (GCPM, GCINSP, OWNER, SUBREP)
ALL_ROLES = list(ROLES)


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present; role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return uid, role


def require_roles(role_list):
    """Priorities 1-2: header presence/validity, then endpoint role membership."""
    uid, role = authenticate()
    if role not in role_list:
        raise forbidden()
    return uid, role


def check_responsible_party(uid, role, trade):
    """Priority 3 (PRD 2.1): the three responsible-party operations (punch-item
    mark-ready, closeout-document create, lien-waiver submission).
    A SubcontractorRep's X-User-ID is the acting TradePackage's id and the trade
    must be SUBCONTRACTOR; a GCProjectManager may act only on SELF_PERFORMED
    trades."""
    if role == SUBREP:
        if uid != trade["id"] or trade["responsible_type"] != "SUBCONTRACTOR":
            raise not_responsible_party()
    elif role == GCPM:
        if trade["responsible_type"] != "SELF_PERFORMED":
            raise not_responsible_party()
