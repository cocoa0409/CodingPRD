"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import unauthenticated, forbidden

ROLES = ("SchedulingOfficer", "Operator", "PayrollClerk", "UnionRep")

ALL_ROLES = ["SchedulingOfficer", "Operator", "PayrollClerk", "UnionRep"]
READ_SO_OP_UR = ["SchedulingOfficer", "Operator", "UnionRep"]


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise unauthenticated()
    return {"user_id": uid, "role": role}


def require_roles(auth, roles):
    if auth["role"] not in roles:
        raise forbidden()
