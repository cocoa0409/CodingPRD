"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Operator), and for tests that do
# NOT exercise Guest/Facilitator ownership (e.g. 401/403/404 checks).
TEST_USERS = {
    # Operator: opaque identity — the shared constant is the canonical form.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    # Anonymous: no authenticated identity (used for self-registration & 401 checks).
    "anonymous_headers": build_user_headers("anonymous", "Anonymous"),
    # Guest: entity_backed — shared constant is a fallback for NON-ownership tests only
    # (e.g. an Operator-exclusive op attempted as Guest, which is denied before ownership).
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    # Facilitator: entity_backed, read-only — fallback for non-ownership reads.
    "facilitator_headers": build_user_headers("test-facilitator-1", "Facilitator"),
}


def make_guest_headers(user_id: str) -> dict:
    """For Guest (entity_backed:Guest). Pass the actual Guest.id as user_id
    whenever the call is ownership-gated (booking/payment/waiver/transport/add-on writes)."""
    return build_user_headers(user_id, "Guest")


def make_facilitator_headers(user_id: str) -> dict:
    """For Facilitator (entity_backed:Facilitator). Pass the actual Facilitator.id
    when reading own profile/schedule."""
    return build_user_headers(user_id, "Facilitator")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    """Operator identity is opaque; any string works."""
    return build_user_headers(user_id, "Operator")


def make_anonymous_headers() -> dict:
    return build_user_headers("anonymous", "Anonymous")
