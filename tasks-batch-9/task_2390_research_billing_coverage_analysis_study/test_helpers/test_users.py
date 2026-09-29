"""Pre-built role headers for every role in the PRD.

All five roles are operator identities rather than persisted records, and there
is no resource-ownership check anywhere in this system.  The acting identifier
is only ever compared against another recorded operator identifier, for the
three segregation-of-duties rules: an analysis may not be approved by its
preparer, a built budget may not be executed by its builder, and an audit
finding may not be responded to by its opener.  For those three comparisons the
tests need two *distinct* identifiers per role, which the ``*_ONE`` / ``*_TWO``
constants below supply.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- Acting user identifiers ---------------------------------------------
MANAGER_ONE = "mgr_1"
MANAGER_TWO = "mgr_2"
REVIEWER_ONE = "reviewer_1"
REVIEWER_TWO = "reviewer_2"
ANALYST_ONE = "analyst_1"
ANALYST_TWO = "analyst_2"
COORDINATOR_ONE = "coord_1"
COORDINATOR_SEVEN = "coord_7"
LIAISON_ONE = "liaison_1"
LIAISON_TWO = "liaison_2"

# --- Role names, spelled exactly as the PRD spells them ------------------
ROLE_MANAGER = "ResearchBillingManager"
ROLE_ANALYST = "CoverageAnalyst"
ROLE_REVIEWER = "ComplianceReviewer"
ROLE_COORDINATOR = "StudyCoordinator"
ROLE_LIAISON = "AuditLiaison"


TEST_USERS = {
    # Primary operator per role.
    "manager_headers": build_user_headers(MANAGER_ONE, ROLE_MANAGER),
    "analyst_headers": build_user_headers(ANALYST_ONE, ROLE_ANALYST),
    "reviewer_headers": build_user_headers(REVIEWER_ONE, ROLE_REVIEWER),
    "coordinator_headers": build_user_headers(COORDINATOR_ONE, ROLE_COORDINATOR),
    "liaison_headers": build_user_headers(LIAISON_ONE, ROLE_LIAISON),
    # Second, distinct operator per role — the segregation-of-duties counterparty.
    "manager_two_headers": build_user_headers(MANAGER_TWO, ROLE_MANAGER),
    "analyst_two_headers": build_user_headers(ANALYST_TWO, ROLE_ANALYST),
    "reviewer_two_headers": build_user_headers(REVIEWER_TWO, ROLE_REVIEWER),
    "coordinator_seven_headers": build_user_headers(
        COORDINATOR_SEVEN, ROLE_COORDINATOR
    ),
    "liaison_two_headers": build_user_headers(LIAISON_TWO, ROLE_LIAISON),
}


def make_manager_headers(user_id: str) -> dict:
    """Headers for a ResearchBillingManager acting as ``user_id``."""
    return build_user_headers(user_id, ROLE_MANAGER)


def make_analyst_headers(user_id: str) -> dict:
    """Headers for a CoverageAnalyst acting as ``user_id``."""
    return build_user_headers(user_id, ROLE_ANALYST)


def make_reviewer_headers(user_id: str) -> dict:
    """Headers for a ComplianceReviewer acting as ``user_id``."""
    return build_user_headers(user_id, ROLE_REVIEWER)


def make_coordinator_headers(user_id: str) -> dict:
    """Headers for a StudyCoordinator acting as ``user_id``."""
    return build_user_headers(user_id, ROLE_COORDINATOR)


def make_liaison_headers(user_id: str) -> dict:
    """Headers for an AuditLiaison acting as ``user_id``."""
    return build_user_headers(user_id, ROLE_LIAISON)


# Headers whose X-User-Role is not one of the five declared role names.
UNDECLARED_ROLE_HEADERS = build_user_headers("someone_1", "BillingClerk")

# Headers with no auth fields at all.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
