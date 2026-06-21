"""Pre-built role headers for every role in the PRD.

The Operator role is opaque: X-User-ID is never compared to any entity, so a
shared constant is the canonical form. The Guest role is entity_backed:Guest —
ownership checks compare the reservation's guest_id to X-User-ID — so any
ownership-gated call MUST use make_guest_headers(guest_id) with the real
Guest.id. The shared guest constant is a fallback only for tests whose success
does not depend on owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator: shared constant is canonical.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    # entity_backed guest: shared constant for non-ownership tests only.
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
}


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    """Operator headers. X-User-ID is opaque and not tied to any entity."""
    return build_user_headers(user_id, "Operator")


def make_guest_headers(user_id: str) -> dict:
    """For the Guest role (entity_backed:Guest). Pass the actual Guest.id as
    user_id whenever the call is ownership-gated (reservation/add-on/payment)."""
    return build_user_headers(user_id, "Guest")
