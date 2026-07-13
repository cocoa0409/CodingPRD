"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# Lifeguard ownership. BeachCaptain, WaterQualityInspector, ParkingClerk, and
# Public are opaque identities; their X-User-ID is not tied to any entity.
TEST_USERS = {
    "beach_captain_headers": build_user_headers("test-captain-1", "BeachCaptain"),
    # Lifeguard is entity_backed:Lifeguard — this shared constant is a fallback
    # only for tests that never touch a Lifeguard ownership check.
    "lifeguard_headers": build_user_headers("test-lifeguard-1", "Lifeguard"),
    "inspector_headers": build_user_headers("test-inspector-1", "WaterQualityInspector"),
    "parking_clerk_headers": build_user_headers("test-clerk-1", "ParkingClerk"),
    "public_headers": build_user_headers("test-public-1", "Public"),
}


def make_lifeguard_headers(user_id: str) -> dict:
    """For Lifeguard (entity_backed:Lifeguard). Pass the actual Lifeguard.id as
    user_id whenever the call touches a Lifeguard ownership check — i.e. driving
    a Shift or Incident that carries that lifeguard_id (see PRD §2.1)."""
    return build_user_headers(user_id, "Lifeguard")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for an arbitrary (role, user_id) pair."""
    return build_user_headers(user_id, role)
