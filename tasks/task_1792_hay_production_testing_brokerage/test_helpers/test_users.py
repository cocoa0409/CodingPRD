"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are entity-backed and therefore get per-instance builders:
- Grower: X-User-ID IS the acting Grower.id
- Buyer:  X-User-ID IS the acting Buyer.id

For any ownership-gated call (grower creating fields/cuttings, marking or
abandoning a cutting, requesting/disputing/cancelling a baling order;
buyer creating/editing/issuing/accepting/declining its own quotes) the
builder MUST be called with the actual entity id. The shared constants are
a fallback for opaque roles and for tests that never pass an ownership
gate.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "ops_headers": build_user_headers("test-ops-1", "BrokerOps"),
    "tech_headers": build_user_headers("tech-1", "LabTechnician"),
    # Entity-backed roles — fallback ONLY for tests that never exercise
    # ownership (e.g. RBAC probes against non-owned surfaces).
    "grower_headers": build_user_headers("test-grower-1", "Grower"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_grower_headers(grower_id: str) -> dict:
    """Grower headers whose X-User-ID is a real Grower.id.

    Mandatory whenever the call is ownership-gated (field/cutting creation,
    mark-cut, abandon, baling-order request/dispute/cancel).
    """
    return build_user_headers(grower_id, "Grower")


def make_buyer_headers(buyer_id: str) -> dict:
    """Buyer headers whose X-User-ID is a real Buyer.id.

    Mandatory whenever the call is ownership-gated (quote create/patch/
    issue/revise/accept/decline, buyer-scoped reads).
    """
    return build_user_headers(buyer_id, "Buyer")


def make_tech_headers(user_id: str) -> dict:
    """LabTechnician headers with a chosen operator id (opaque role).

    Used to exercise the segregation-of-duties rule, which compares the
    certifier's X-User-ID against the test's resulted_by_user_id.
    """
    return build_user_headers(user_id, "LabTechnician")
