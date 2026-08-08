"""Pre-built role headers for every role in the PRD.

All four roles use an opaque X-User-ID that the server never compares to any
entity id, so shared constants are safe for ownership-agnostic tests. Where a
business rule records the acting X-User-ID (waiver request/approve for
segregation of duties), pass a distinct user id via the per-role builder.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — one stable identity per role.
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-default", "CollectionsClerk"),
    "supervisor_headers": build_user_headers("supervisor-default", "CollectionsSupervisor"),
    "finance_headers": build_user_headers("finance-default", "FinanceOfficer"),
    "admin_headers": build_user_headers("admin-default", "SystemAdmin"),
}

# Headers carrying an X-User-ID but no X-User-Role — for ERR_UNAUTHENTICATED tests.
NO_ROLE_HEADERS = {"X-User-ID": "anon-1"}


def clerk_headers(user_id: str = "clerk-default") -> dict:
    """CollectionsClerk headers; pass a distinct user_id for SoD scenarios."""
    return build_user_headers(user_id, "CollectionsClerk")


def supervisor_headers(user_id: str = "supervisor-default") -> dict:
    """CollectionsSupervisor headers; pass a distinct user_id for SoD scenarios."""
    return build_user_headers(user_id, "CollectionsSupervisor")


def finance_headers(user_id: str = "finance-default") -> dict:
    """FinanceOfficer headers."""
    return build_user_headers(user_id, "FinanceOfficer")


def admin_headers(user_id: str = "admin-default") -> dict:
    """SystemAdmin headers."""
    return build_user_headers(user_id, "SystemAdmin")
