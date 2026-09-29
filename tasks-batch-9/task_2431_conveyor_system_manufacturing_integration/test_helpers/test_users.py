"""Pre-built role headers for every role in the PRD.

All five roles have opaque identity: `X-User-ID` is an opaque operator identifier
that is never resolved to a stored resource. The shared constants below are
therefore the canonical form. The per-role builders exist for the two places where
the raw `X-User-ID` string is load-bearing: the CustomerRep ownership comparison
against a project's `customer_rep_user_id`, and the segregation-of-duties
comparison between a certificate issuer and the recorder of the passing full-rate
commissioning ramp step.
"""

from prd_bench_local_runner.testing import build_user_headers

# Default opaque operator identifiers used by the suite.
DEFAULT_PROJECT_DIRECTOR_USER_ID = "pd-001"
DEFAULT_DESIGN_ENGINEER_USER_ID = "de-001"
DEFAULT_SHOP_SUPERVISOR_USER_ID = "ss-001"
DEFAULT_SITE_MANAGER_USER_ID = "sm-001"
DEFAULT_CUSTOMER_REP_USER_ID = "cust-rep-77"

# A second director identifier, for tests that need an issuer distinct from
# another director, and a second customer representative for ownership tests.
ALT_PROJECT_DIRECTOR_USER_ID = "pd-002"
ALT_CUSTOMER_REP_USER_ID = "cust-rep-88"
ALT_SITE_MANAGER_USER_ID = "sm-002"


TEST_USERS = {
    "project_director_headers": build_user_headers(
        DEFAULT_PROJECT_DIRECTOR_USER_ID, "ProjectDirector"
    ),
    "design_engineer_headers": build_user_headers(
        DEFAULT_DESIGN_ENGINEER_USER_ID, "DesignEngineer"
    ),
    "shop_supervisor_headers": build_user_headers(
        DEFAULT_SHOP_SUPERVISOR_USER_ID, "ShopSupervisor"
    ),
    "site_manager_headers": build_user_headers(
        DEFAULT_SITE_MANAGER_USER_ID, "SiteManager"
    ),
    "customer_rep_headers": build_user_headers(
        DEFAULT_CUSTOMER_REP_USER_ID, "CustomerRep"
    ),
}


def make_project_director_headers(user_id: str) -> dict:
    """ProjectDirector headers for an explicit opaque operator identifier."""
    return build_user_headers(user_id, "ProjectDirector")


def make_design_engineer_headers(user_id: str) -> dict:
    """DesignEngineer headers for an explicit opaque operator identifier."""
    return build_user_headers(user_id, "DesignEngineer")


def make_shop_supervisor_headers(user_id: str) -> dict:
    """ShopSupervisor headers for an explicit opaque operator identifier."""
    return build_user_headers(user_id, "ShopSupervisor")


def make_site_manager_headers(user_id: str) -> dict:
    """SiteManager headers for an explicit opaque operator identifier.

    Pass the identifier that must land in `recorded_by_user_id` on a ramp step.
    """
    return build_user_headers(user_id, "SiteManager")


def make_customer_rep_headers(user_id: str) -> dict:
    """CustomerRep headers for an explicit opaque operator identifier.

    Pass the project's `customer_rep_user_id` whenever the call is ownership-gated.
    """
    return build_user_headers(user_id, "CustomerRep")


ALL_ROLE_NAMES = (
    "ProjectDirector",
    "DesignEngineer",
    "ShopSupervisor",
    "SiteManager",
    "CustomerRep",
)
