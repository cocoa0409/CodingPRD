"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed (their X-User-ID must equal a real entity id when the
call is ownership-gated): PublicAdjuster -> Adjuster.id, Client -> Client.id.
FirmPrincipal, Carrier, and System are opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "public_adjuster_headers": build_user_headers("test-adjuster-1", "PublicAdjuster"),
    "client_headers": build_user_headers("test-client-1", "Client"),
    # opaque roles: shared constant is the canonical form.
    "firm_principal_headers": build_user_headers("test-firm-1", "FirmPrincipal"),
    "carrier_headers": build_user_headers("test-carrier-1", "Carrier"),
    "system_headers": build_user_headers("test-system-1", "System"),
}


# Per-instance builders — required for every entity_backed role.
def make_public_adjuster_headers(user_id: str) -> dict:
    """For PublicAdjuster (entity_backed:Adjuster). Pass the actual Adjuster.id as
    user_id whenever the call is ownership-gated (create/file/counter/accept, etc.)."""
    return build_user_headers(user_id, "PublicAdjuster")


def make_client_headers(user_id: str) -> dict:
    """For Client (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated (e.g. contract sign)."""
    return build_user_headers(user_id, "Client")


def make_firm_principal_headers(user_id: str) -> dict:
    """FirmPrincipal is opaque; this builder lets a test control the operator id
    (e.g. to differ from a claim's accepted_by_user_id for segregation of duties)."""
    return build_user_headers(user_id, "FirmPrincipal")


def make_carrier_headers(user_id: str) -> dict:
    """Carrier is opaque; builder for controlling the operator id."""
    return build_user_headers(user_id, "Carrier")
