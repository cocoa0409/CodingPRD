"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are `identity: opaque` — the X-User-ID is an opaque operator
identifier not tied to any persisted entity — so shared constants are the
canonical form. The server records X-User-ID onto deal.analyst_id (deal
creation), deal.asset_manager_id (submit-underwriting, via the
X-AssetManager-ID header), and ICVote.voter_user_id (vote time); tests thread
the same literal ids so ownership checks pass.
"""
from prd_bench_local_runner.testing import build_user_headers

ANALYST_USER_ID = "u-analyst-1"
ASSET_MANAGER_USER_ID = "u-am-1"
IC_MEMBER_1_USER_ID = "u-ic-1"
IC_MEMBER_2_USER_ID = "u-ic-2"
IC_CHAIR_USER_ID = "u-chair-1"
ADMIN_USER_ID = "u-admin-1"

TEST_USERS = {
    "analyst_headers": build_user_headers(ANALYST_USER_ID, "Analyst"),
    "asset_manager_headers": build_user_headers(ASSET_MANAGER_USER_ID, "AssetManager"),
    "ic_member_headers": build_user_headers(IC_MEMBER_1_USER_ID, "IC_Member"),
    "ic_member_2_headers": build_user_headers(IC_MEMBER_2_USER_ID, "IC_Member"),
    "ic_chair_headers": build_user_headers(IC_CHAIR_USER_ID, "IC_Chair"),
    "admin_headers": build_user_headers(ADMIN_USER_ID, "Admin"),
}


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Analyst")


def make_asset_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AssetManager")


def make_ic_member_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IC_Member")


def make_ic_chair_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IC_Chair")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Admin")


def submit_underwriting_headers(asset_manager_id: str = ASSET_MANAGER_USER_ID) -> dict:
    """Analyst headers plus the X-AssetManager-ID header that submit-underwriting
    records onto deal.asset_manager_id (PRD §3.1)."""
    headers = dict(TEST_USERS["analyst_headers"])
    headers["X-AssetManager-ID"] = asset_manager_id
    return headers
