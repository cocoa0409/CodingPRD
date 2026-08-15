"""Pre-built role headers for every role in the PRD (section 2.1).

Every role in this PRD is opaque: X-User-ID is never compared to any
entity's id. The shared constants below are therefore canonical for all
non-ownership calls. The per-user builders exist for workflows that record
or compare X-User-ID (drawer opener/counter segregation, and the Customer
own-resource rule for preorder pay/cancel and exchange creation).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "director_headers": build_user_headers("test-director-1", "ActivitiesDirector"),
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "coordinator_headers": build_user_headers(
        "test-coordinator-1", "LicensingCoordinator"
    ),
    "treasurer_headers": build_user_headers("test-treasurer-1", "Treasurer"),
    "cashier_headers": build_user_headers("test-cashier-1", "StudentCashier"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ActivitiesDirector")


def make_store_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LicensingCoordinator")


def make_treasurer_headers(user_id: str) -> dict:
    """For drawer counting: pass a user_id that differs from the opener's."""
    return build_user_headers(user_id, "Treasurer")


def make_cashier_headers(user_id: str) -> dict:
    """For drawer opening: the recorded opened_by_user_id is this user_id."""
    return build_user_headers(user_id, "StudentCashier")


def make_customer_headers(user_id: str) -> dict:
    """For Customer own-resource calls: user_id must equal customer_user_id."""
    return build_user_headers(user_id, "Customer")
