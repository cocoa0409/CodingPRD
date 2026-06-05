"""Pre-built role headers for every role in the PRD.

All three roles carry an opaque identity (PRD §2.1): X-User-ID is an opaque
operator id never compared to any entity id, except the segregation-of-duties
control (§2.7). Tests therefore pick the user id they need per-call; these
shared constants cover the common default identities used across setups.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constant headers — opaque roles, safe everywhere.
TEST_USERS = {
    "owner_headers": build_user_headers("owner-1", "Owner"),
    "contractor_headers": build_user_headers("gc-1", "Contractor"),
    "architect_headers": build_user_headers("arch-1", "Architect"),
}


def make_owner_headers(user_id: str) -> dict:
    """Owner headers with an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "Owner")


def make_contractor_headers(user_id: str) -> dict:
    """Contractor headers with an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "Contractor")


def make_architect_headers(user_id: str) -> dict:
    """Architect headers with an explicit opaque X-User-ID."""
    return build_user_headers(user_id, "Architect")
