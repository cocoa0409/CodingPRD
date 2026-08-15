"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque: X-User-ID is never compared to any entity id (PRD
§2.1), so shared constants are safe for every call. Builders accepting an
explicit user_id exist for segregation-of-duties tests (core-test submitter vs
locker, PRD §3.4) where the user id value itself matters.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ranch_manager_headers": build_user_headers("rm-1", "RanchManager"),
    "range_hand_headers": build_user_headers("rh-1", "RangeHand"),
    "wool_pool_operator_headers": build_user_headers("wpo-1", "WoolPoolOperator"),
    "grazing_client_headers": build_user_headers("gc-1", "GrazingClient"),
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
}


def make_ranch_manager_headers(user_id: str) -> dict:
    """RanchManager headers with an explicit user id (core-test SoD, PRD §3.4)."""
    return build_user_headers(user_id, "RanchManager")


def make_range_hand_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RangeHand")


def make_wool_pool_operator_headers(user_id: str) -> dict:
    """WoolPoolOperator headers with an explicit user id (SoD anchor, PRD §3.4)."""
    return build_user_headers(user_id, "WoolPoolOperator")


def make_grazing_client_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GrazingClient")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
