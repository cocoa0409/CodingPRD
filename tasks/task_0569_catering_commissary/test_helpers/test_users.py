"""Pre-built role headers for every role in the PRD.

Every role's identity is opaque (PRD Section 2.1): X-User-ID is never compared
to any resource id, so shared constants are sufficient for all tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "kitchen_manager_headers": build_user_headers("test-kitchen-1", "KitchenManager"),
    "sales_manager_headers": build_user_headers("test-sales-1", "SalesManager"),
    "event_captain_headers": build_user_headers("test-captain-1", "EventCaptain"),
}

# No-auth headers for unauthenticated-path tests (PRD Section 2.1).
NO_AUTH_HEADERS: dict = {}
