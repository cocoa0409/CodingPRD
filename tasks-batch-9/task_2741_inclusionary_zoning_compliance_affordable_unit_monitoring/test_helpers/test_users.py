"""Pre-built authentication headers for every actor used by the suite.

Every request carries X-User-ID and X-User-Role.  Four of the five roles are
opaque operator identities; the Resident role is entity-backed, so a Resident's
X-User-ID must be the id of the Household row it acts for and can only be built
once that household exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- operator identities -----------------------------------------------------
PROGRAM_ADMIN_USER_ID = "pa-1"
COMPLIANCE_OFFICER_USER_ID = "hco-1"
SECOND_COMPLIANCE_OFFICER_USER_ID = "hco-2"
DEVELOPER_USER_ID = "dev-1"
SECOND_DEVELOPER_USER_ID = "dev-2"
FUND_AUDITOR_USER_ID = "aud-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "program_admin": build_user_headers(
        PROGRAM_ADMIN_USER_ID, UserRole.PROGRAM_ADMINISTRATOR.value
    ),
    "compliance_officer": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, UserRole.HOUSING_COMPLIANCE_OFFICER.value
    ),
    "second_compliance_officer": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_USER_ID, UserRole.HOUSING_COMPLIANCE_OFFICER.value
    ),
    "developer": build_user_headers(DEVELOPER_USER_ID, UserRole.DEVELOPER.value),
    "rival_developer": build_user_headers(
        SECOND_DEVELOPER_USER_ID, UserRole.DEVELOPER.value
    ),
    "fund_auditor": build_user_headers(FUND_AUDITOR_USER_ID, UserRole.FUND_AUDITOR.value),
}


def make_resident_headers(household_id: str) -> Dict[str, str]:
    """Resident headers whose X-User-ID is the acting household's own id."""
    return build_user_headers(household_id, UserRole.RESIDENT.value)


# --- malformed / unrecognised identities -------------------------------------
# A request that carries neither authentication header at all.
NO_AUTH_HEADERS: Dict[str, str] = {}

# A request that names a declared role but supplies an empty user id.
EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": UserRole.DEVELOPER.value,
    "Content-Type": "application/json",
}

# A request whose role name is not one of the five declared roles.
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers("insp-1", "HousingInspector")
