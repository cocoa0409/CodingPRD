"""Caller identities and the two headers every request carries.

PRD section 2.1 states that every request carries ``X-User-ID`` and ``X-Role``, so the
header builders below emit exactly those two names (plus ``Content-Type``). Seven of the
nine roles are opaque strings, but ``Landowner`` must carry the Landowner record id and
``TowerCompanyAgent`` must carry the TowerCompany record id, so those two roles get
factory functions that take the entity id instead of a fixed constant.
"""

from typing import Dict, Optional

from .types import Role

CONTENT_TYPE = "application/json"

# Opaque user ids for the seven roles whose header value is not tied to a record.
TEST_USERS: Dict[str, str] = {
    Role.PLATFORM_ADMIN.value: "admin-root",
    Role.ACQUISITION_ANALYST.value: "analyst-quinn",
    Role.PORTFOLIO_MANAGER.value: "pm-alice",
    Role.TREASURY_OFFICER.value: "treasury-tess",
    Role.TITLE_OFFICER.value: "title-tom",
    Role.LENDER.value: "lender-hudson",
    Role.SERVICING_AGENT.value: "servicer-sam",
}

# Two distinct PortfolioManager users: the duty split described in PRD section 2.12 is
# enforced between users of one role, so approval and close need separate identities.
PM_APPROVER_USER_ID = "pm-alice"
PM_CLOSER_USER_ID = "pm-bob"


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build the two identity headers the PRD requires, plus a JSON content type."""
    return {"X-User-ID": user_id, "X-Role": role, "Content-Type": CONTENT_TYPE}


def make_platform_admin_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return make_headers(Role.PLATFORM_ADMIN.value, user_id or TEST_USERS[Role.PLATFORM_ADMIN.value])


def make_acquisition_analyst_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return make_headers(Role.ACQUISITION_ANALYST.value, user_id or TEST_USERS[Role.ACQUISITION_ANALYST.value])


def make_portfolio_manager_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return make_headers(Role.PORTFOLIO_MANAGER.value, user_id or PM_APPROVER_USER_ID)


def make_treasury_officer_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return make_headers(Role.TREASURY_OFFICER.value, user_id or TEST_USERS[Role.TREASURY_OFFICER.value])


def make_title_officer_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return make_headers(Role.TITLE_OFFICER.value, user_id or TEST_USERS[Role.TITLE_OFFICER.value])


def make_lender_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return make_headers(Role.LENDER.value, user_id or TEST_USERS[Role.LENDER.value])


def make_servicing_agent_headers(user_id: Optional[str] = None) -> Dict[str, str]:
    return make_headers(Role.SERVICING_AGENT.value, user_id or TEST_USERS[Role.SERVICING_AGENT.value])


def make_landowner_headers(landowner_id: str) -> Dict[str, str]:
    """Landowner callers identify themselves with the Landowner record id."""
    return make_headers(Role.LANDOWNER.value, landowner_id)


def make_tower_company_agent_headers(tower_company_id: str) -> Dict[str, str]:
    """TowerCompanyAgent callers identify themselves with the TowerCompany record id."""
    return make_headers(Role.TOWER_COMPANY_AGENT.value, tower_company_id)


# Convenience aliases for the two named PortfolioManager identities.
def make_approving_manager_headers() -> Dict[str, str]:
    return make_portfolio_manager_headers(PM_APPROVER_USER_ID)


def make_closing_manager_headers() -> Dict[str, str]:
    return make_portfolio_manager_headers(PM_CLOSER_USER_ID)


def make_headers_without_role(user_id: Optional[str] = None) -> Dict[str, str]:
    """Omit ``X-Role`` entirely, which PRD section 2.1 treats as unauthenticated."""
    headers = {"Content-Type": CONTENT_TYPE}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    return headers


def make_headers_with_unknown_role(user_id: str = "nobody-1") -> Dict[str, str]:
    """Carry an ``X-Role`` value that is not one of the nine declared roles."""
    return make_headers("GroundskeeperGeneral", user_id)


__all__ = [
    "TEST_USERS",
    "PM_APPROVER_USER_ID",
    "PM_CLOSER_USER_ID",
    "make_headers",
    "make_platform_admin_headers",
    "make_acquisition_analyst_headers",
    "make_portfolio_manager_headers",
    "make_treasury_officer_headers",
    "make_title_officer_headers",
    "make_lender_headers",
    "make_servicing_agent_headers",
    "make_landowner_headers",
    "make_tower_company_agent_headers",
    "make_approving_manager_headers",
    "make_closing_manager_headers",
    "make_headers_without_role",
    "make_headers_with_unknown_role",
]
