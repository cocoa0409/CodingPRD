"""
Pre-built auth headers for each role, plus builders for the two entity-backed roles.

Five of the seven roles carry an opaque operator identifier that is never compared
to any row's id, so a module-level constant header dict is correct for them. The
two entity-backed roles are different: for a SchoolBillingAgent the X-User-ID must
be the id of the acting ApprovedPrivateSchool, and for a ParentGuardian it must be
the id of the acting Student. Those two therefore have builder functions and MUST
NOT be used through a shared constant.

Segregation of duties is enforced by user identity within a single role, so this
module supplies two distinct TeamChair identities and two distinct FiscalOfficer
identities.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FISCAL_OFFICER,
    ROLE_HEARING_ADJUDICATOR,
    ROLE_PARENT_GUARDIAN,
    ROLE_PLACEMENT_COORDINATOR,
    ROLE_SCHOOL_BILLING_AGENT,
    ROLE_SYSTEM_ADMIN,
    ROLE_TEAM_CHAIR,
)

# ─── Opaque operator identifiers ──────────────────────────────────────────────
USER_COORDINATOR = "u-coord-1"
USER_COORDINATOR_2 = "u-coord-2"
USER_TEAM_CHAIR = "u-chair-1"
USER_TEAM_CHAIR_2 = "u-chair-2"
USER_FISCAL_OFFICER = "u-fiscal-1"
USER_FISCAL_OFFICER_2 = "u-fiscal-2"
USER_HEARING_ADJUDICATOR = "u-hearing-1"
USER_SYSTEM_ADMIN = "u-admin-1"

TEST_USERS = {
    "coordinator": USER_COORDINATOR,
    "coordinator_2": USER_COORDINATOR_2,
    "team_chair": USER_TEAM_CHAIR,
    "team_chair_2": USER_TEAM_CHAIR_2,
    "fiscal_officer": USER_FISCAL_OFFICER,
    "fiscal_officer_2": USER_FISCAL_OFFICER_2,
    "hearing_adjudicator": USER_HEARING_ADJUDICATOR,
    "system_admin": USER_SYSTEM_ADMIN,
}

# ─── Ready-made headers for the five opaque-identifier roles ───────────────────
COORDINATOR_HEADERS = build_user_headers(USER_COORDINATOR, ROLE_PLACEMENT_COORDINATOR)
COORDINATOR_2_HEADERS = build_user_headers(
    USER_COORDINATOR_2, ROLE_PLACEMENT_COORDINATOR
)
TEAM_CHAIR_HEADERS = build_user_headers(USER_TEAM_CHAIR, ROLE_TEAM_CHAIR)
TEAM_CHAIR_2_HEADERS = build_user_headers(USER_TEAM_CHAIR_2, ROLE_TEAM_CHAIR)
FISCAL_OFFICER_HEADERS = build_user_headers(USER_FISCAL_OFFICER, ROLE_FISCAL_OFFICER)
FISCAL_OFFICER_2_HEADERS = build_user_headers(
    USER_FISCAL_OFFICER_2, ROLE_FISCAL_OFFICER
)
HEARING_ADJUDICATOR_HEADERS = build_user_headers(
    USER_HEARING_ADJUDICATOR, ROLE_HEARING_ADJUDICATOR
)
SYSTEM_ADMIN_HEADERS = build_user_headers(USER_SYSTEM_ADMIN, ROLE_SYSTEM_ADMIN)


# ─── Entity-backed role header builders ───────────────────────────────────────
def make_school_billing_agent_headers(school_id: str) -> dict:
    """
    Headers for a SchoolBillingAgent acting as the school whose id is school_id.

    X-User-ID is the id of the acting ApprovedPrivateSchool, so callers must pass
    a real school id captured from a create response - never a fixed string.
    """
    return build_user_headers(school_id, ROLE_SCHOOL_BILLING_AGENT)


def make_parent_guardian_headers(student_id: str) -> dict:
    """
    Headers for a ParentGuardian acting for the student whose id is student_id.

    X-User-ID is the id of the acting Student, so callers must pass a real student
    id captured from a create response - never a fixed string.
    """
    return build_user_headers(student_id, ROLE_PARENT_GUARDIAN)


# ─── Malformed / unusable header sets for the authentication rung ──────────────
NO_HEADERS: dict = {"Content-Type": "application/json"}

MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_PLACEMENT_COORDINATOR,
    "Content-Type": "application/json",
}

EMPTY_USER_ID_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PLACEMENT_COORDINATOR,
    "Content-Type": "application/json",
}

MISSING_ROLE_HEADERS = {
    "X-User-ID": USER_COORDINATOR,
    "Content-Type": "application/json",
}

EMPTY_ROLE_HEADERS = {
    "X-User-ID": USER_COORDINATOR,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

UNKNOWN_ROLE_HEADERS = build_user_headers(USER_COORDINATOR, "DistrictSuperintendent")


def headers_for_role(role: str, entity_id: str = None) -> dict:
    """
    Build headers for an arbitrary role name.

    entity_id is required for the two entity-backed roles and ignored otherwise.
    """
    if role == ROLE_SCHOOL_BILLING_AGENT:
        assert entity_id, "SchoolBillingAgent needs the acting school id"
        return make_school_billing_agent_headers(entity_id)
    if role == ROLE_PARENT_GUARDIAN:
        assert entity_id, "ParentGuardian needs the acting student id"
        return make_parent_guardian_headers(entity_id)
    return {
        ROLE_PLACEMENT_COORDINATOR: COORDINATOR_HEADERS,
        ROLE_TEAM_CHAIR: TEAM_CHAIR_HEADERS,
        ROLE_FISCAL_OFFICER: FISCAL_OFFICER_HEADERS,
        ROLE_HEARING_ADJUDICATOR: HEARING_ADJUDICATOR_HEADERS,
        ROLE_SYSTEM_ADMIN: SYSTEM_ADMIN_HEADERS,
    }[role]
