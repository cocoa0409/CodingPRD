"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use opaque operator identifiers (PRD §2.1: `X-User-ID` is an
opaque operator identifier not tied to any persisted entity), so shared
constants are the canonical form. Per-user builders exist for segregation-of-
duties scenarios, where a specific operator identity must propose vs approve.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "accountant_headers": build_user_headers("acct-1", "RevenueAccountant"),
    "manager_headers": build_user_headers("mgr-1", "RevenueManager"),
    "reviewer_headers": build_user_headers("rev-1", "ContractReviewer"),
    "controller_headers": build_user_headers("ctrl-1", "Controller"),
    "admin_headers": build_user_headers("ops-1", "SystemAdmin"),
}


def make_accountant_headers(user_id: str) -> dict:
    """RevenueAccountant headers for a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "RevenueAccountant")


def make_manager_headers(user_id: str) -> dict:
    """RevenueManager headers for a specific operator id (SoD scenarios)."""
    return build_user_headers(user_id, "RevenueManager")


def make_reviewer_headers(user_id: str) -> dict:
    """ContractReviewer headers for a specific operator id (task ownership, SoD)."""
    return build_user_headers(user_id, "ContractReviewer")


def make_controller_headers(user_id: str) -> dict:
    """Controller headers for a specific operator id (assemble/finalize SoD)."""
    return build_user_headers(user_id, "Controller")


def make_admin_headers(user_id: str) -> dict:
    """SystemAdmin headers for a specific operator id (logical clock only)."""
    return build_user_headers(user_id, "SystemAdmin")
