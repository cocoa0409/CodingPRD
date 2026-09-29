"""Header builders for the nine declared roles.

Every request must carry ``X-User-ID`` and ``X-User-Role``.  For eight of the
nine roles the user id is an opaque operator identifier that the server never
compares to any entity id, so a fixed literal is fine.  For
``HospitalReferralClerk`` the user id **is** the id of the acting hospital
partner, so that role gets a builder that takes the hospital id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ALLOCATION_SPECIALIST,
    ROLE_AUTHORIZATION_SPECIALIST,
    ROLE_DONOR_COORDINATOR,
    ROLE_HOSPITAL_REFERRAL_CLERK,
    ROLE_MEDICAL_DIRECTOR,
    ROLE_OPO_ADMIN,
    ROLE_RECOVERY_LOGISTICS,
    ROLE_REFERRAL_COORDINATOR,
    ROLE_SEROLOGY_LAB,
)

# --- Canonical operator identifiers ----------------------------------------
ADMIN_USER = "admin-1"
COORDINATOR_USER = "coord-1"
COORDINATOR_USER_2 = "coord-2"
COORDINATOR_USER_9 = "coord-9"
LAB_USER = "lab-1"
DIRECTOR_USER = "md-1"
DIRECTOR_USER_2 = "md-2"
AUTH_USER_1 = "auth-1"
AUTH_USER_2 = "auth-2"
AUTH_USER_3 = "auth-3"
DONOR_USER = "donor-1"
ALLOCATION_USER = "alloc-1"
LOGISTICS_USER = "logi-1"


def make_opo_admin_headers(user_id: str = ADMIN_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_OPO_ADMIN)


def make_referral_coordinator_headers(user_id: str = COORDINATOR_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_REFERRAL_COORDINATOR)


def make_serology_lab_headers(user_id: str = LAB_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SEROLOGY_LAB)


def make_medical_director_headers(user_id: str = DIRECTOR_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_MEDICAL_DIRECTOR)


def make_authorization_specialist_headers(user_id: str = AUTH_USER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_AUTHORIZATION_SPECIALIST)


def make_donor_coordinator_headers(user_id: str = DONOR_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DONOR_COORDINATOR)


def make_allocation_specialist_headers(user_id: str = ALLOCATION_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ALLOCATION_SPECIALIST)


def make_recovery_logistics_headers(user_id: str = LOGISTICS_USER) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_RECOVERY_LOGISTICS)


def make_hospital_referral_clerk_headers(hospital_id: str) -> Dict[str, str]:
    """The clerk's ``X-User-ID`` is the id of the hospital partner it acts for."""
    return build_user_headers(hospital_id, ROLE_HOSPITAL_REFERRAL_CLERK)


def make_anonymous_headers() -> Dict[str, str]:
    """No identity headers at all -- the shape that must draw 401."""
    return {"Content-Type": "application/json"}


def make_headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary declared role name."""
    return build_user_headers(user_id, role)
