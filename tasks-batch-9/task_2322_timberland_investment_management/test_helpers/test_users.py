"""Acting users and header builders for the seven roles of PRD §2.1.

`X-User-ID` is an opaque operator identifier that is never compared to any
entity's `id`; the only comparisons the system makes on it are the
segregation-of-duties comparisons of PRD §2.10. Distinct identifiers per role
instance therefore matter only where duty separation or custody stamping is
under test.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

FUND_ADMIN = "FundAdmin"
ACQUISITION_ANALYST = "AcquisitionAnalyst"
INVESTMENT_COMMITTEE = "InvestmentCommittee"
FOREST_MANAGER = "ForestManager"
CERTIFICATION_AUDITOR = "CertificationAuditor"
CARBON_DEVELOPER = "CarbonDeveloper"
INDEPENDENT_APPRAISER = "IndependentAppraiser"

ALL_ROLES = (
    FUND_ADMIN,
    ACQUISITION_ANALYST,
    INVESTMENT_COMMITTEE,
    FOREST_MANAGER,
    CERTIFICATION_AUDITOR,
    CARBON_DEVELOPER,
    INDEPENDENT_APPRAISER,
)

# A role string outside the seven declared values.
UNKNOWN_ROLE = "TimberBroker"

# Stable operator identifiers used across the suite.
ADMIN_1 = "admin-1"
ANALYST_1 = "analyst-1"
ANALYST_2 = "analyst-2"
IC_1 = "ic-1"
IC_2 = "ic-2"
FM_1 = "fm-1"
FM_2 = "fm-2"
MANAGER_1 = "manager-1"
CA_1 = "ca-1"
CA_2 = "ca-2"
AUDITOR_1 = "auditor-1"
AUDITOR_2 = "auditor-2"
CARBON_1 = "carbon-1"
APPRAISER_1 = "appraiser-1"
APPRAISER_2 = "appraiser-2"
APPRAISER_3 = "appraiser-3"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "fund_admin": {"user_id": ADMIN_1, "role": FUND_ADMIN},
    "analyst": {"user_id": ANALYST_1, "role": ACQUISITION_ANALYST},
    "analyst_other": {"user_id": ANALYST_2, "role": ACQUISITION_ANALYST},
    "committee": {"user_id": IC_1, "role": INVESTMENT_COMMITTEE},
    "committee_other": {"user_id": IC_2, "role": INVESTMENT_COMMITTEE},
    "forest_manager": {"user_id": FM_1, "role": FOREST_MANAGER},
    "forest_manager_other": {"user_id": FM_2, "role": FOREST_MANAGER},
    "auditor": {"user_id": CA_1, "role": CERTIFICATION_AUDITOR},
    "auditor_other": {"user_id": CA_2, "role": CERTIFICATION_AUDITOR},
    "carbon_developer": {"user_id": CARBON_1, "role": CARBON_DEVELOPER},
    "appraiser": {"user_id": APPRAISER_1, "role": INDEPENDENT_APPRAISER},
    "appraiser_other": {"user_id": APPRAISER_2, "role": INDEPENDENT_APPRAISER},
    "appraiser_third": {"user_id": APPRAISER_3, "role": INDEPENDENT_APPRAISER},
}


def headers_for(user_id: str, role: str) -> Dict[str, str]:
    """Well-formed headers declaring an acting user and the capacity it acts in."""
    return build_user_headers(user_id, role)


def make_fund_admin_headers(user_id: str = ADMIN_1) -> Dict[str, str]:
    return build_user_headers(user_id, FUND_ADMIN)


def make_analyst_headers(user_id: str = ANALYST_1) -> Dict[str, str]:
    return build_user_headers(user_id, ACQUISITION_ANALYST)


def make_committee_headers(user_id: str = IC_1) -> Dict[str, str]:
    return build_user_headers(user_id, INVESTMENT_COMMITTEE)


def make_forest_manager_headers(user_id: str = FM_1) -> Dict[str, str]:
    return build_user_headers(user_id, FOREST_MANAGER)


def make_auditor_headers(user_id: str = CA_1) -> Dict[str, str]:
    return build_user_headers(user_id, CERTIFICATION_AUDITOR)


def make_carbon_developer_headers(user_id: str = CARBON_1) -> Dict[str, str]:
    return build_user_headers(user_id, CARBON_DEVELOPER)


def make_appraiser_headers(user_id: str = APPRAISER_1) -> Dict[str, str]:
    return build_user_headers(user_id, INDEPENDENT_APPRAISER)


def make_unknown_role_headers(user_id: str = ADMIN_1, role: str = UNKNOWN_ROLE) -> Dict[str, str]:
    """Headers whose `X-User-Role` is not one of the seven declared role strings."""
    return {"X-User-ID": user_id, "X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_user_id(role: str = FUND_ADMIN) -> Dict[str, str]:
    """Headers that declare a valid role but omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str = ADMIN_1) -> Dict[str, str]:
    """Headers that declare an acting user but omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


ROLE_HEADER_BUILDERS = {
    FUND_ADMIN: make_fund_admin_headers,
    ACQUISITION_ANALYST: make_analyst_headers,
    INVESTMENT_COMMITTEE: make_committee_headers,
    FOREST_MANAGER: make_forest_manager_headers,
    CERTIFICATION_AUDITOR: make_auditor_headers,
    CARBON_DEVELOPER: make_carbon_developer_headers,
    INDEPENDENT_APPRAISER: make_appraiser_headers,
}


def default_headers_for_role(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    builder = ROLE_HEADER_BUILDERS[role]
    return builder() if user_id is None else builder(user_id)
