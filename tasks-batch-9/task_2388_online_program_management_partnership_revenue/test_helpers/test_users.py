"""Acting principals and header builders.

Five of the six roles carry an opaque operator identifier that the server never
compares to any entity id (PRD 2.1). The sixth, `PartnerAccountLead`, is
different: its `X-User-ID` *is* the id of the acting `Partnership`, so its
headers must be built per partnership.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_FACULTY_CHAIR,
    ROLE_PARTNER_ACCOUNT_LEAD,
    ROLE_PLATFORM_ADMIN,
    ROLE_UNIVERSITY_BURSAR,
    ROLE_UNIVERSITY_PROVOST,
)

PLATFORM_ADMIN_USER_ID = "admin-1"
PROVOST_USER_ID = "provost-1"
SECOND_PROVOST_USER_ID = "provost-2"
BURSAR_USER_ID = "bursar-1"
SECOND_BURSAR_USER_ID = "bursar-2"
FACULTY_CHAIR_USER_ID = "faculty-1"
COMPLIANCE_AUDITOR_USER_ID = "auditor-1"
SECOND_COMPLIANCE_AUDITOR_USER_ID = "auditor-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {"user_id": PLATFORM_ADMIN_USER_ID, "role": ROLE_PLATFORM_ADMIN},
    "provost": {"user_id": PROVOST_USER_ID, "role": ROLE_UNIVERSITY_PROVOST},
    "second_provost": {"user_id": SECOND_PROVOST_USER_ID, "role": ROLE_UNIVERSITY_PROVOST},
    "bursar": {"user_id": BURSAR_USER_ID, "role": ROLE_UNIVERSITY_BURSAR},
    "second_bursar": {"user_id": SECOND_BURSAR_USER_ID, "role": ROLE_UNIVERSITY_BURSAR},
    "faculty_chair": {"user_id": FACULTY_CHAIR_USER_ID, "role": ROLE_FACULTY_CHAIR},
    "compliance_auditor": {"user_id": COMPLIANCE_AUDITOR_USER_ID, "role": ROLE_COMPLIANCE_AUDITOR},
    "second_compliance_auditor": {
        "user_id": SECOND_COMPLIANCE_AUDITOR_USER_ID,
        "role": ROLE_COMPLIANCE_AUDITOR,
    },
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_provost_headers(user_id: str = PROVOST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_UNIVERSITY_PROVOST)


def make_bursar_headers(user_id: str = BURSAR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_UNIVERSITY_BURSAR)


def make_faculty_chair_headers(user_id: str = FACULTY_CHAIR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FACULTY_CHAIR)


def make_compliance_auditor_headers(user_id: str = COMPLIANCE_AUDITOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_COMPLIANCE_AUDITOR)


def make_partner_account_lead_headers(partnership_id: str) -> Dict[str, str]:
    """Headers for the partner's account lead, whose identity is its partnership id."""
    return build_user_headers(partnership_id, ROLE_PARTNER_ACCOUNT_LEAD)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for negative tests that need an arbitrary id / role pairing."""
    return build_user_headers(user_id, role)
