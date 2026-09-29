"""Canonical test identities and the header builders that authenticate them.

Every request carries `X-User-ID` and `X-User-Role` (PRD §2.1). Five of the six
roles are opaque operator identities: any non-empty id is accepted for them and
the id is retained only for audit stamping and segregation-of-duties checks. The
sixth role, Vendor, is different: a Vendor caller's `X-User-ID` must be the id of
the Vendor row it is acting for, so vendor headers are always built from a
vendor id returned by the API.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ------------------------------------------------------- operator identities
ADMIN_USER_ID = "U-ADMIN-1"
OFFICER_USER_ID = "U-OFFICER-1"
OFFICER_2_USER_ID = "U-OFFICER-2"
REVIEWER_USER_ID = "U-REVIEWER-1"
REVIEWER_2_USER_ID = "U-REVIEWER-2"
HEARING_OFFICER_USER_ID = "U-HEARING-1"
HEARING_OFFICER_2_USER_ID = "U-HEARING-2"
DEBARMENT_AUTHORITY_USER_ID = "U-DEBAR-1"
DEBARMENT_AUTHORITY_2_USER_ID = "U-DEBAR-2"

# An operator who wears two hats: used to provoke the segregation-of-duties
# conflicts, where the same natural person appears on both sides of a matter.
DUAL_HAT_USER_ID = "U-DUAL-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": ADMIN_USER_ID, "role": UserRole.SYSTEM_ADMIN.value},
    "officer": {"user_id": OFFICER_USER_ID, "role": UserRole.PROCUREMENT_OFFICER.value},
    "officer_2": {
        "user_id": OFFICER_2_USER_ID,
        "role": UserRole.PROCUREMENT_OFFICER.value,
    },
    "reviewer": {
        "user_id": REVIEWER_USER_ID,
        "role": UserRole.RESPONSIBILITY_REVIEWER.value,
    },
    "reviewer_2": {
        "user_id": REVIEWER_2_USER_ID,
        "role": UserRole.RESPONSIBILITY_REVIEWER.value,
    },
    "hearing_officer": {
        "user_id": HEARING_OFFICER_USER_ID,
        "role": UserRole.HEARING_OFFICER.value,
    },
    "hearing_officer_2": {
        "user_id": HEARING_OFFICER_2_USER_ID,
        "role": UserRole.HEARING_OFFICER.value,
    },
    "debarment_authority": {
        "user_id": DEBARMENT_AUTHORITY_USER_ID,
        "role": UserRole.DEBARMENT_AUTHORITY.value,
    },
    "debarment_authority_2": {
        "user_id": DEBARMENT_AUTHORITY_2_USER_ID,
        "role": UserRole.DEBARMENT_AUTHORITY.value,
    },
}


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Authentication headers for an arbitrary id/role pair."""
    return build_user_headers(user_id, role)


def make_vendor_headers(vendor_id: str) -> Dict[str, str]:
    """Headers for a Vendor caller acting for its own Vendor row."""
    return build_user_headers(vendor_id, UserRole.VENDOR.value)


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PROCUREMENT_OFFICER.value)


def make_reviewer_headers(user_id: str = REVIEWER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.RESPONSIBILITY_REVIEWER.value)


def make_hearing_officer_headers(
    user_id: str = HEARING_OFFICER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.HEARING_OFFICER.value)


def make_debarment_authority_headers(
    user_id: str = DEBARMENT_AUTHORITY_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.DEBARMENT_AUTHORITY.value)


# Convenient module-level singletons for the five opaque roles.
ADMIN_HEADERS = make_admin_headers()
OFFICER_HEADERS = make_officer_headers()
OFFICER_2_HEADERS = make_officer_headers(OFFICER_2_USER_ID)
REVIEWER_HEADERS = make_reviewer_headers()
REVIEWER_2_HEADERS = make_reviewer_headers(REVIEWER_2_USER_ID)
HEARING_OFFICER_HEADERS = make_hearing_officer_headers()
HEARING_OFFICER_2_HEADERS = make_hearing_officer_headers(HEARING_OFFICER_2_USER_ID)
DEBARMENT_AUTHORITY_HEADERS = make_debarment_authority_headers()
DEBARMENT_AUTHORITY_2_HEADERS = make_debarment_authority_headers(
    DEBARMENT_AUTHORITY_2_USER_ID
)

# Headers with no credentials at all, for the unauthenticated pathway.
NO_AUTH_HEADERS: Dict[str, str] = {}
