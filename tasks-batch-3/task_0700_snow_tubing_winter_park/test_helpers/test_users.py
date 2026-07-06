"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (GuestPatron, GroupHost): their X-User-ID must be
the acting Patron's id whenever an ownership check applies. For those roles use
the make_*_headers(patron_id) builders. The shared TEST_USERS constants are
only safe for opaque roles or for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "anonymous_headers": build_user_headers("bootstrap-anon-1", "Anonymous"),
    "park_operator_headers": build_user_headers("test-operator-1", "ParkOperator"),
    "safety_marshal_headers": build_user_headers("test-marshal-1", "SafetyMarshal"),
    # Entity-backed roles — shared constants are FALLBACKS for non-ownership tests
    # only (e.g. forbidden-role checks). Ownership-gated calls must use the builders.
    "guest_patron_headers": build_user_headers("test-guest-1", "GuestPatron"),
    "group_host_headers": build_user_headers("test-host-1", "GroupHost"),
}


# Per-instance builders — required for every entity_backed role.

def make_guest_patron_headers(patron_id: str) -> dict:
    """For GuestPatron (entity_backed:Patron). Pass the acting Patron.id as
    user_id whenever the call is ownership-gated (ticket holder ownership)."""
    return build_user_headers(patron_id, "GuestPatron")


def make_group_host_headers(patron_id: str) -> dict:
    """For GroupHost (entity_backed:Patron). Pass the acting Patron.id as
    user_id whenever the call is ownership-gated (reservation host ownership)."""
    return build_user_headers(patron_id, "GroupHost")


def make_park_operator_headers(user_id: str = "test-operator-1") -> dict:
    """For ParkOperator (opaque). Identifier is recorded but never compared."""
    return build_user_headers(user_id, "ParkOperator")


def make_safety_marshal_headers(user_id: str = "test-marshal-1") -> dict:
    """For SafetyMarshal (opaque). Identifier is recorded but never compared."""
    return build_user_headers(user_id, "SafetyMarshal")


def make_anonymous_headers(user_id: str = "bootstrap-anon-1") -> dict:
    """For Anonymous (opaque bootstrap identity)."""
    return build_user_headers(user_id, "Anonymous")
