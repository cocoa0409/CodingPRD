"""Pre-built role headers for every role in the PRD.

All five roles use an OPAQUE X-User-ID (PRD §2.1): the server never compares
X-User-ID to an entity id for ownership. The only rule that reads X-User-ID is
the four-eyes segregation-of-duties check at adoption, which compares the
adopting X-User-ID against the plan's recorded created_by_user_id (PRD §2.10).
Fixtures therefore create plans with the Cartographer's stable "u_cart" id and
adopt with the Chair's distinct "u_chair" id so SoD passes by default; the SoD
denial test deliberately adopts with "u_cart".
"""
from prd_bench_local_runner.testing import build_user_headers

# Stable per-role user ids used consistently across fixtures.
USER_IDS = {
    "Cartographer": "u_cart",
    "Demographer": "u_demo",
    "CommissionChair": "u_chair",
    "ElectionClerk": "u_clerk",
    "PublicParticipant": "u_public",
}

TEST_USERS = {
    "cartographer_headers": build_user_headers(USER_IDS["Cartographer"], "Cartographer"),
    "demographer_headers": build_user_headers(USER_IDS["Demographer"], "Demographer"),
    "chair_headers": build_user_headers(USER_IDS["CommissionChair"], "CommissionChair"),
    "clerk_headers": build_user_headers(USER_IDS["ElectionClerk"], "ElectionClerk"),
    "public_headers": build_user_headers(USER_IDS["PublicParticipant"], "PublicParticipant"),
}


def make_headers(role: str, user_id: str) -> dict:
    """Build headers for a role with an explicit X-User-ID.

    Needed for the four-eyes SoD scenarios where the acting user id must equal
    (or differ from) a plan's created_by_user_id.
    """
    return build_user_headers(user_id, role)
