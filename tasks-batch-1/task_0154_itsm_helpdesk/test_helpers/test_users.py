"""Pre-built role headers for every role in the PRD.

All five roles (PRD §2.1) use an opaque identity model: X-User-ID is never tied
to any persisted entity row, so shared constants are the canonical form for
every role. Where a test needs a SPECIFIC opaque id (e.g. ownership comparisons
on requester_id, or the SoD comparison on raised_by_user_id), it builds headers
inline via build_user_headers(<id>, <role>).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "requester_headers": build_user_headers("req-shared", "Requester"),
    "agent_headers": build_user_headers("agent-shared", "Agent"),
    "change_manager_headers": build_user_headers("cm-shared", "ChangeManager"),
    "cab_member_headers": build_user_headers("cab-shared", "CabMember"),
    "platform_admin_headers": build_user_headers("admin-shared", "PlatformAdmin"),
}


def requester(user_id: str) -> dict:
    """Headers for a Requester with a specific opaque X-User-ID (ownership-sensitive ops)."""
    return build_user_headers(user_id, "Requester")


def agent(user_id: str = "agent-shared") -> dict:
    return build_user_headers(user_id, "Agent")


def change_manager(user_id: str) -> dict:
    """Headers for a ChangeManager with a specific opaque X-User-ID (recorded as raised_by_user_id)."""
    return build_user_headers(user_id, "ChangeManager")


def cab_member(user_id: str) -> dict:
    """Headers for a CabMember with a specific opaque X-User-ID (recorded as voter_user_id; SoD)."""
    return build_user_headers(user_id, "CabMember")


def platform_admin(user_id: str = "admin-shared") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
