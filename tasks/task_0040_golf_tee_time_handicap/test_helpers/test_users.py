"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ProShop, Anonymous), and for tests
# that do not exercise golfer ownership.
TEST_USERS = {
    "proshop_headers": build_user_headers("test-proshop-1", "ProShop"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # Golfer is entity_backed; shared constant is a fallback for non-ownership tests only.
    "golfer_headers": build_user_headers("test-golfer-1", "Golfer"),
}


def make_proshop_headers(user_id: str = "test-proshop-1") -> dict:
    """ProShop is opaque; X-User-ID is not tied to any entity."""
    return build_user_headers(user_id, "ProShop")


def make_anonymous_headers(user_id: str = "test-anon-1") -> dict:
    """Anonymous is opaque; X-User-ID is not tied to any entity."""
    return build_user_headers(user_id, "Anonymous")


def make_golfer_headers(user_id: str) -> dict:
    """For Golfer (entity_backed:Golfer). Pass the actual Golfer.id as user_id
    whenever the call is ownership-gated (e.g. booking-create, cancel)."""
    return build_user_headers(user_id, "Golfer")
