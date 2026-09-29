"""Pre-built authentication headers for every role.

Five roles carry an opaque operator identifier in ``X-User-ID`` and get a stable
constant here. Three roles are entity-backed — an ``AgencyRepresentative`` must
present an Agency id, an ``Appraiser`` an Appraiser id and a ``Bidder`` a Bidder
id — so those get per-instance builders that thread a freshly created entity id
into the header.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque operator identities
# ---------------------------------------------------------------------------

REAL_PROPERTY_OFFICER_USER_ID = "officer-1"
BOARD_CLERK_USER_ID = "clerk-1"
COMPLIANCE_MONITOR_USER_ID = "compliance-1"
FINANCE_OFFICER_USER_ID = "finance-1"
SYSTEM_ADMINISTRATOR_USER_ID = "sysadmin-1"

#: Distinct clerk identities, so segregation-of-duties pairs can be separated.
CLERK_ADOPT_USER_ID = "clerk-adopt-1"
CLERK_DETERMINE_USER_ID = "clerk-determine-1"
CLERK_DETERMINE_2_USER_ID = "clerk-determine-2"
CLERK_AUTHORIZE_USER_ID = "clerk-authorize-1"
CLERK_AWARD_USER_ID = "clerk-award-1"
CLERK_AWARD_2_USER_ID = "clerk-award-2"
CLERK_WITHDRAW_USER_ID = "clerk-withdraw-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "real_property_officer": build_user_headers(
        REAL_PROPERTY_OFFICER_USER_ID, UserRole.REAL_PROPERTY_OFFICER.value
    ),
    "board_clerk": build_user_headers(
        BOARD_CLERK_USER_ID, UserRole.BOARD_CLERK.value
    ),
    "compliance_monitor": build_user_headers(
        COMPLIANCE_MONITOR_USER_ID, UserRole.COMPLIANCE_MONITOR.value
    ),
    "finance_officer": build_user_headers(
        FINANCE_OFFICER_USER_ID, UserRole.FINANCE_OFFICER.value
    ),
    "system_administrator": build_user_headers(
        SYSTEM_ADMINISTRATOR_USER_ID, UserRole.SYSTEM_ADMINISTRATOR.value
    ),
    "clerk_adopt": build_user_headers(
        CLERK_ADOPT_USER_ID, UserRole.BOARD_CLERK.value
    ),
    "clerk_determine": build_user_headers(
        CLERK_DETERMINE_USER_ID, UserRole.BOARD_CLERK.value
    ),
    "clerk_determine_2": build_user_headers(
        CLERK_DETERMINE_2_USER_ID, UserRole.BOARD_CLERK.value
    ),
    "clerk_authorize": build_user_headers(
        CLERK_AUTHORIZE_USER_ID, UserRole.BOARD_CLERK.value
    ),
    "clerk_award": build_user_headers(
        CLERK_AWARD_USER_ID, UserRole.BOARD_CLERK.value
    ),
    "clerk_award_2": build_user_headers(
        CLERK_AWARD_2_USER_ID, UserRole.BOARD_CLERK.value
    ),
    "clerk_withdraw": build_user_headers(
        CLERK_WITHDRAW_USER_ID, UserRole.BOARD_CLERK.value
    ),
}

#: Shorthand aliases for the five opaque roles.
OFFICER_HEADERS = TEST_USERS["real_property_officer"]
CLERK_HEADERS = TEST_USERS["board_clerk"]
COMPLIANCE_HEADERS = TEST_USERS["compliance_monitor"]
FINANCE_HEADERS = TEST_USERS["finance_officer"]
ADMIN_HEADERS = TEST_USERS["system_administrator"]

CLERK_ADOPT_HEADERS = TEST_USERS["clerk_adopt"]
CLERK_DETERMINE_HEADERS = TEST_USERS["clerk_determine"]
CLERK_DETERMINE_2_HEADERS = TEST_USERS["clerk_determine_2"]
CLERK_AUTHORIZE_HEADERS = TEST_USERS["clerk_authorize"]
CLERK_AWARD_HEADERS = TEST_USERS["clerk_award"]
CLERK_AWARD_2_HEADERS = TEST_USERS["clerk_award_2"]
CLERK_WITHDRAW_HEADERS = TEST_USERS["clerk_withdraw"]


# ---------------------------------------------------------------------------
# Entity-backed identities
# ---------------------------------------------------------------------------


def make_agency_representative_headers(agency_id: str) -> Dict[str, str]:
    """Headers for an AgencyRepresentative acting for the agency with this id."""
    return build_user_headers(agency_id, UserRole.AGENCY_REPRESENTATIVE.value)


def make_appraiser_headers(appraiser_id: str) -> Dict[str, str]:
    """Headers for an Appraiser acting as the appraiser with this id."""
    return build_user_headers(appraiser_id, UserRole.APPRAISER.value)


def make_bidder_headers(bidder_id: str) -> Dict[str, str]:
    """Headers for a Bidder acting as the bidder with this id."""
    return build_user_headers(bidder_id, UserRole.BIDDER.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id and role pair."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying a user id but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
