"""Authentication and role resolution (PRD Section 2.1).

Every request carries ``X-User-ID`` and ``X-User-Role``. ``PharmacyAdmin``
and ``DiversionOfficer`` are opaque roles (no staff-roster lookup). The four
entity-backed roles resolve ``X-User-ID`` to a ``StaffMember`` row that must
exist, be active, and have a ``staff_role`` matching the header enum.
"""

from flask import request

import db
from errors import err_unauthenticated, err_forbidden, err_role_mismatch


ALL_ROLES = [
    "PharmacyAdmin", "Prescriber", "Pharmacist",
    "PharmacyTechnician", "Nurse", "DiversionOfficer",
]

# Header role -> StaffMember.staff_role enum (note TECHNICIAN spelling).
ENTITY_ROLE_ENUM = {
    "Prescriber": "PRESCRIBER",
    "Pharmacist": "PHARMACIST",
    "PharmacyTechnician": "TECHNICIAN",
    "Nurse": "NURSE",
}


def authenticate(allowed_roles):
    """Run the auth priority chain; returns (user_id, role, staff_or_None)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise err_unauthenticated()
    if role not in allowed_roles:
        raise err_forbidden()
    staff = None
    if role in ENTITY_ROLE_ENUM:
        staff = db.staff.get(uid)
        if staff is None or not staff.get("active", False):
            raise err_role_mismatch()
        if staff.get("staff_role") != ENTITY_ROLE_ENUM[role]:
            raise err_role_mismatch()
    return uid, role, staff
