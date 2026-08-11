"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership of a specific resource.
TEST_USERS = {
    # Opaque role: X-User-ID is never compared to an entity id (PRD §2.1).
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed:CorporateAccount — fallback for non-ownership tests only.
    "organizer_headers": build_user_headers("test-organizer-1", "Organizer"),
    # entity_backed:Therapist — fallback for non-ownership tests only.
    "therapist_headers": build_user_headers("test-therapist-1", "Therapist"),
}

# No identity headers at all — for unauthenticated-request tests.
NO_HEADERS: dict = {}


def make_organizer_headers(account_id: str) -> dict:
    """Organizer headers bound to a real CorporateAccount id (PRD §2.1:
    X-User-ID is the id of the acting CorporateAccount)."""
    return build_user_headers(account_id, "Organizer")


def make_therapist_headers(therapist_id: str) -> dict:
    """Therapist headers bound to a real Therapist id (PRD §2.1:
    X-User-ID is the id of the acting Therapist)."""
    return build_user_headers(therapist_id, "Therapist")


def make_platform_admin_headers(operator_id: str = "test-admin-1") -> dict:
    """PlatformAdmin headers; the id is opaque and never ownership-checked."""
    return build_user_headers(operator_id, "PlatformAdmin")
