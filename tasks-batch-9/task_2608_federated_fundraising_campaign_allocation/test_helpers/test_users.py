"""Header builders for the six roles.

Three roles are backed by persisted entities, so their ``X-User-ID`` must be the
id of the specific row the caller is acting as (PRD 2.1): a ``CampaignCoordinator``
row, an ``Agency`` row, or a ``Panelist`` row. Tests that write to an
ownership-gated resource MUST pass the real entity id, never a shared constant,
otherwise ownership checks fail for reasons unrelated to the behaviour under
test. The three opaque roles may use a stable operator identifier.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers (PRD 2.1: never compared to any entity id).
UNITED_FUND_ADMIN_ID = "op-united-fund-admin"
FINANCE_REVIEWER_ID = "op-finance-reviewer"
ALLOCATIONS_DIRECTOR_ID = "op-allocations-director"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "united_fund_admin": {
        "user_id": UNITED_FUND_ADMIN_ID,
        "role": UserRole.UNITED_FUND_ADMIN.value,
    },
    "finance_reviewer": {
        "user_id": FINANCE_REVIEWER_ID,
        "role": UserRole.FINANCE_REVIEWER.value,
    },
    "allocations_director": {
        "user_id": ALLOCATIONS_DIRECTOR_ID,
        "role": UserRole.ALLOCATIONS_DIRECTOR.value,
    },
}


# --- Opaque-identity roles -------------------------------------------
def make_admin_headers(user_id: str = UNITED_FUND_ADMIN_ID) -> Dict[str, str]:
    """Headers for `UnitedFundAdmin`, whose `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.UNITED_FUND_ADMIN.value)


def make_finance_reviewer_headers(user_id: str = FINANCE_REVIEWER_ID) -> Dict[str, str]:
    """Headers for `FinanceReviewer`, whose `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.FINANCE_REVIEWER.value)


def make_allocations_director_headers(
    user_id: str = ALLOCATIONS_DIRECTOR_ID,
) -> Dict[str, str]:
    """Headers for `AllocationsDirector`, whose `X-User-ID` is opaque."""
    return build_user_headers(user_id, UserRole.ALLOCATIONS_DIRECTOR.value)


# --- Entity-backed roles ---------------------------------------------
def make_coordinator_headers(coordinator_id: str) -> Dict[str, str]:
    """Headers for the `CampaignCoordinator` row identified by `coordinator_id`."""
    return build_user_headers(coordinator_id, UserRole.CAMPAIGN_COORDINATOR.value)


def make_agency_rep_headers(agency_id: str) -> Dict[str, str]:
    """Headers for the `AgencyRepresentative` acting as the `Agency` row `agency_id`."""
    return build_user_headers(agency_id, UserRole.AGENCY_REPRESENTATIVE.value)


def make_panelist_headers(panelist_id: str) -> Dict[str, str]:
    """Headers for the `VolunteerPanelist` acting as the `Panelist` row `panelist_id`."""
    return build_user_headers(panelist_id, UserRole.VOLUNTEER_PANELIST.value)
