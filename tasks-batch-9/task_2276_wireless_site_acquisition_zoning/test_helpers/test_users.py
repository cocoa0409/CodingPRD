"""Actor identities and header builders.

The PRD authenticates by two headers, `X-User-ID` and `X-User-Role`, treats all
identity as opaque, and records the acting `X-User-ID` into ownership and
authorship fields, so each actor below has a stable identifier.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

# Roles exactly as the PRD spells them.
ROLE_RF_ENGINEER = "RfEngineer"
ROLE_SITE_ACQUISITION_AGENT = "SiteAcquisitionAgent"
ROLE_ZONING_PLANNER = "ZoningPlanner"
ROLE_STRUCTURAL_ENGINEER = "StructuralEngineer"
ROLE_ENVIRONMENTAL_REVIEWER = "EnvironmentalReviewer"
ROLE_CONSTRUCTION_MANAGER = "ConstructionManager"
ROLE_PROGRAM_DIRECTOR = "ProgramDirector"

ALL_ROLES = (
    ROLE_RF_ENGINEER,
    ROLE_SITE_ACQUISITION_AGENT,
    ROLE_ZONING_PLANNER,
    ROLE_STRUCTURAL_ENGINEER,
    ROLE_ENVIRONMENTAL_REVIEWER,
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_PROGRAM_DIRECTOR,
)

# Recorded operator identifiers.
AGENT_OWNER = "agent-001"       # owns every candidate the suite creates
AGENT_PEER = "agent-002"        # a second agent who owns nothing
DIRECTOR = "director-001"       # distinct from AGENT_OWNER
ANALYST = "sengr-001"           # performs structural analyses
DESIGNER = "sengr-002"          # authors modification designs
CERTIFIER = "sengr-003"         # certifies designs
PLANNER = "planner-001"
PLANNER_ALT = "planner-002"
RF_ENGINEER = "rfe-001"
ENV_REVIEWER = "env-001"
CONSTRUCTION_MANAGER = "cm-001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "rf_engineer": {"user_id": RF_ENGINEER, "role": ROLE_RF_ENGINEER},
    "agent_owner": {"user_id": AGENT_OWNER, "role": ROLE_SITE_ACQUISITION_AGENT},
    "agent_peer": {"user_id": AGENT_PEER, "role": ROLE_SITE_ACQUISITION_AGENT},
    "zoning_planner": {"user_id": PLANNER, "role": ROLE_ZONING_PLANNER},
    "zoning_planner_alt": {"user_id": PLANNER_ALT, "role": ROLE_ZONING_PLANNER},
    "analyst": {"user_id": ANALYST, "role": ROLE_STRUCTURAL_ENGINEER},
    "designer": {"user_id": DESIGNER, "role": ROLE_STRUCTURAL_ENGINEER},
    "certifier": {"user_id": CERTIFIER, "role": ROLE_STRUCTURAL_ENGINEER},
    "environmental_reviewer": {
        "user_id": ENV_REVIEWER,
        "role": ROLE_ENVIRONMENTAL_REVIEWER,
    },
    "construction_manager": {
        "user_id": CONSTRUCTION_MANAGER,
        "role": ROLE_CONSTRUCTION_MANAGER,
    },
    "program_director": {"user_id": DIRECTOR, "role": ROLE_PROGRAM_DIRECTOR},
}


def _headers(role: str, user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, role)


def make_rf_engineer_headers(user_id: str = RF_ENGINEER) -> Dict[str, str]:
    return _headers(ROLE_RF_ENGINEER, user_id)


def make_site_acquisition_agent_headers(user_id: str = AGENT_OWNER) -> Dict[str, str]:
    return _headers(ROLE_SITE_ACQUISITION_AGENT, user_id)


def make_zoning_planner_headers(user_id: str = PLANNER) -> Dict[str, str]:
    return _headers(ROLE_ZONING_PLANNER, user_id)


def make_structural_engineer_headers(user_id: str = ANALYST) -> Dict[str, str]:
    return _headers(ROLE_STRUCTURAL_ENGINEER, user_id)


def make_environmental_reviewer_headers(user_id: str = ENV_REVIEWER) -> Dict[str, str]:
    return _headers(ROLE_ENVIRONMENTAL_REVIEWER, user_id)


def make_construction_manager_headers(
    user_id: str = CONSTRUCTION_MANAGER,
) -> Dict[str, str]:
    return _headers(ROLE_CONSTRUCTION_MANAGER, user_id)


def make_program_director_headers(user_id: str = DIRECTOR) -> Dict[str, str]:
    return _headers(ROLE_PROGRAM_DIRECTOR, user_id)


def make_headers(role: Optional[str], user_id: Optional[str] = None) -> Dict[str, str]:
    """Build headers for an arbitrary role, or omit identity headers entirely.

    Passing ``role=None`` yields a request that carries no `X-User-Role`, which
    the PRD treats as an unauthenticated call.
    """
    if role is None:
        return {"Content-Type": "application/json"}
    return _headers(role, user_id or "anon-001")


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

__all__ = [
    "ROLE_RF_ENGINEER",
    "ROLE_SITE_ACQUISITION_AGENT",
    "ROLE_ZONING_PLANNER",
    "ROLE_STRUCTURAL_ENGINEER",
    "ROLE_ENVIRONMENTAL_REVIEWER",
    "ROLE_CONSTRUCTION_MANAGER",
    "ROLE_PROGRAM_DIRECTOR",
    "ALL_ROLES",
    "AGENT_OWNER",
    "AGENT_PEER",
    "DIRECTOR",
    "ANALYST",
    "DESIGNER",
    "CERTIFIER",
    "PLANNER",
    "PLANNER_ALT",
    "RF_ENGINEER",
    "ENV_REVIEWER",
    "CONSTRUCTION_MANAGER",
    "TEST_USERS",
    "NO_AUTH_HEADERS",
    "make_rf_engineer_headers",
    "make_site_acquisition_agent_headers",
    "make_zoning_planner_headers",
    "make_structural_engineer_headers",
    "make_environmental_reviewer_headers",
    "make_construction_manager_headers",
    "make_program_director_headers",
    "make_headers",
]
