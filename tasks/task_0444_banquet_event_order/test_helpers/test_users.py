"""Pre-built role headers for every role in the Banquet Event Order PRD (§2.1).

All four roles — PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk —
carry an OPAQUE identity: the accompanying X-User-ID is an operator identifier
that the server never compares to any persisted entity, and no resource
ownership is derived from it. Authorization is decided purely by role. The
shared constant is therefore the canonical form for every call; no per-instance
entity-backed header builder is needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "sales_manager_headers": build_user_headers("test-sales-1", "SalesManager"),
    "banquet_captain_headers": build_user_headers("test-captain-1", "BanquetCaptain"),
    "accounting_clerk_headers": build_user_headers("test-clerk-1", "AccountingClerk"),
}


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_sales_manager_headers(user_id: str = "test-sales-1") -> dict:
    """SalesManager is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "SalesManager")


def make_banquet_captain_headers(user_id: str = "test-captain-1") -> dict:
    """BanquetCaptain is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "BanquetCaptain")


def make_accounting_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    """AccountingClerk is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "AccountingClerk")


# Headers carrying an unknown role — used to exercise ERR_UNAUTHENTICATED
# (PRD §2.1: a request whose X-User-Role does not name a known role is rejected).
UNKNOWN_ROLE_HEADERS = build_user_headers("test-ghost-1", "NoSuchRole")
