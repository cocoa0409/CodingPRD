"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identifiers: the server never compares
X-User-ID to any resource's id. The identifier is still recorded on layup
sessions (laminator_id) and inspections (inspector_id), and the
segregation-of-duties rule compares those two recorded values — so the
laminator and inspector personas must use distinct user ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Named operator personas. op-lam-1 performs layup; op-qi-1 inspects.
LAMINATOR_USER_ID = "op-lam-1"
INSPECTOR_USER_ID = "op-qi-1"

TEST_USERS = {
    "shop_manager_headers": build_user_headers("op-sm-1", "ShopManager"),
    "tooling_engineer_headers": build_user_headers("op-te-1", "ToolingEngineer"),
    "laminator_headers": build_user_headers(LAMINATOR_USER_ID, "Laminator"),
    "cure_technician_headers": build_user_headers("op-ct-1", "CureTechnician"),
    "quality_inspector_headers": build_user_headers(INSPECTOR_USER_ID, "QualityInspector"),
    "ehs_officer_headers": build_user_headers("op-ehs-1", "EHSOfficer"),
}


def make_laminator_headers(user_id: str) -> dict:
    """Laminator headers for an explicit operator id (SoD scenarios)."""
    return build_user_headers(user_id, "Laminator")


def make_inspector_headers(user_id: str) -> dict:
    """QualityInspector headers for an explicit operator id (SoD scenarios).

    Passing the laminator's user id here reproduces the forbidden
    same-person layup-then-inspect path.
    """
    return build_user_headers(user_id, "QualityInspector")
