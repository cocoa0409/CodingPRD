"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, every request carries X-User-Role + X-User-ID. All three roles are
"opaque": X-User-ID is an operator identifier, never compared to any entity id.
SoD checks (§2.9) compare X-User-ID against recorded actor fields.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (all roles here are opaque per PRD §2.1).
TEST_USERS = {
    "pm_headers": build_user_headers("pm-1", "OwnerRepPM"),
    "pm2_headers": build_user_headers("pm-2", "OwnerRepPM"),
    "exec_headers": build_user_headers("exec-1", "OwnerRepExecutive"),
    "owner_headers": build_user_headers("owner-1", "Owner"),
}


# Per-instance builders — allow tests to pin a specific X-User-ID for SoD scenarios.
def make_pm_headers(user_id: str) -> dict:
    """OwnerRepPM headers with a specific X-User-ID (for SoD pairing)."""
    return build_user_headers(user_id, "OwnerRepPM")


def make_exec_headers(user_id: str) -> dict:
    """OwnerRepExecutive headers with a specific X-User-ID (for SoD pairing)."""
    return build_user_headers(user_id, "OwnerRepExecutive")


def make_owner_headers(user_id: str) -> dict:
    """Owner headers with a specific X-User-ID (for SoD pairing)."""
    return build_user_headers(user_id, "Owner")
