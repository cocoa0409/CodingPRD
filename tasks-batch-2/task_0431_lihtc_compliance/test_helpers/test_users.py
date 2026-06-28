"""Pre-built role headers for the LIHTC Compliance API (PRD §2.1).

There are exactly two roles, both with **opaque** identity: OwnerAgent and StateHFA. The
server never compares either X-User-ID to any entity's id; it only records the value (e.g.
as a Finding's origin_agent_id) and compares two such opaque identifiers to each other for
the segregation-of-duties check (PRD §3.9). Because identity is opaque, the shared TEST_USERS
constants are the canonical form for ordinary calls.

The one place the actual X-User-ID value matters is segregation of duties: the StateHFA that
reports a Finding must differ from the StateHFA that created the underlying chain. For those
tests, mint distinct headers with make_state_hfa_headers("hfa-1") / make_state_hfa_headers("hfa-2").
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical form for opaque roles.
TEST_USERS = {
    "owner_agent_headers": build_user_headers("owner-agent-1", "OwnerAgent"),
    "state_hfa_headers": build_user_headers("state-hfa-1", "StateHFA"),
}


def make_owner_agent_headers(user_id: str = "owner-agent-1") -> dict:
    """Headers for an OwnerAgent with a chosen opaque X-User-ID."""
    return build_user_headers(user_id, "OwnerAgent")


def make_state_hfa_headers(user_id: str = "state-hfa-1") -> dict:
    """Headers for a StateHFA with a chosen opaque X-User-ID. Used by segregation-of-duties
    tests to distinguish the originating actor (e.g. 'hfa-1') from a different reporter
    (e.g. 'hfa-2')."""
    return build_user_headers(user_id, "StateHFA")


# Convenience distinct StateHFA identities for segregation-of-duties scenarios (PRD §3.9).
STATE_HFA_1 = make_state_hfa_headers("hfa-1")
STATE_HFA_2 = make_state_hfa_headers("hfa-2")

# A request with no authentication headers (PRD §2.1 ERR_UNAUTHENTICATED test).
NO_AUTH_HEADERS: dict = {}
