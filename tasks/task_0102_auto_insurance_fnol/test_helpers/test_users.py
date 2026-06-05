"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are opaque operator identities (ClaimsSupervisor, SubrogationSpecialist):
their X-User-ID is never compared to a persisted entity, so the shared constant is
the canonical form. Two roles are entity_backed on Adjuster (ClaimsAdjuster,
TotalLossAdjuster): when the call is ownership/authorship-gated, the X-User-ID MUST
be the acting Adjuster's id, so a per-instance builder is provided.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these as the canonical form; entity_backed
# roles use them only for tests that do not exercise ownership/authorship.
TEST_USERS = {
    "supervisor_headers": build_user_headers("test-supervisor-1", "ClaimsSupervisor"),
    "subrogation_headers": build_user_headers("test-subrogation-1", "SubrogationSpecialist"),
    # Fallback constants for entity_backed roles (non-ownership tests only).
    "adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "total_loss_headers": build_user_headers("test-total-loss-1", "TotalLossAdjuster"),
}


# Per-instance builders — mandatory for the entity_backed Adjuster roles whenever
# the downstream call compares X-User-ID against an Adjuster.id (authorship,
# "only the assigned adjuster may submit", segregation-of-duties).
def make_claims_adjuster_headers(adjuster_id: str) -> dict:
    """ClaimsAdjuster acting as the given Adjuster (entity_backed:Adjuster)."""
    return build_user_headers(adjuster_id, "ClaimsAdjuster")


def make_total_loss_adjuster_headers(adjuster_id: str) -> dict:
    """TotalLossAdjuster acting as the given Adjuster (entity_backed:Adjuster)."""
    return build_user_headers(adjuster_id, "TotalLossAdjuster")


def make_supervisor_headers(user_id: str = "test-supervisor-1") -> dict:
    """ClaimsSupervisor (opaque identity)."""
    return build_user_headers(user_id, "ClaimsSupervisor")


def make_subrogation_headers(user_id: str = "test-subrogation-1") -> dict:
    """SubrogationSpecialist (opaque identity)."""
    return build_user_headers(user_id, "SubrogationSpecialist")
