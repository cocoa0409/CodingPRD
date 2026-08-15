"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. PropertyOwner is entity-backed: use make_property_owner_headers()
# with the actual PropertyOwner.id whenever the call is ownership-gated.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "clerk_headers": build_user_headers("test-clerk-1", "CityClerk"),
    "engineer_headers": build_user_headers("eng-1", "CityEngineer"),
    "engineer2_headers": build_user_headers("eng-2", "CityEngineer"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "council_headers": build_user_headers("council-1", "CouncilPresident"),
    # Fallback only for non-ownership contexts (e.g. read-only listing calls).
    "owner_headers": build_user_headers("test-owner-1", "PropertyOwner"),
}


def make_property_owner_headers(user_id: str) -> dict:
    """For PropertyOwner (entity-backed): pass the actual PropertyOwner.id as
    user_id whenever the call is ownership-gated (signing, objecting,
    selecting a payment option, posting a payment, owner-path payoff quote)."""
    return build_user_headers(user_id, "PropertyOwner")


def make_engineer_headers(user_id: str) -> dict:
    """For CityEngineer calls where the operator identity matters (change-order
    segregation of duties, estimate submitted_by)."""
    return build_user_headers(user_id, "CityEngineer")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CityClerk")
