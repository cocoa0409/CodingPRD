"""Pre-built role headers for every role in PRD §2.1."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # Opaque role (PRD §2.1): X-User-ID is not compared to any resource's foreign key.
    "admin_headers": build_user_headers("test-admin-1", "HousingAuthorityAdmin"),
    # Opaque role (PRD §2.1).
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # entity_backed role: shared constant is a fallback for NON-ownership tests only.
    "landlord_headers": build_user_headers("test-landlord-1", "Landlord"),
}


def make_landlord_headers(user_id: str) -> dict:
    """For Landlord (entity_backed:Landlord, PRD §2.1). Pass the actual Landlord.id as
    user_id whenever the call is ownership-gated (submit/withdraw/delist/mark-repaired/
    request-reinspection/rent-increase create+withdraw/contract create)."""
    return build_user_headers(user_id, "Landlord")
