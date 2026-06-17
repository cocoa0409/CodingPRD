"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: FieldAdjuster (opaque id), Estimator (X-User-ID is the acting
Estimator record's id), ProductionManager (opaque id). Each request must carry
both X-User-ID and X-User-Role.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# Estimator-ownership against a specific Estimator record.
TEST_USERS = {
    # FieldAdjuster: opaque operator id (PRD §2.1) — shared constant is canonical.
    "field_adjuster_headers": build_user_headers("fa-operator-1", "FieldAdjuster"),
    # ProductionManager: opaque operator id (PRD §2.1) — shared constant is canonical.
    "production_manager_headers": build_user_headers("pm-operator-1", "ProductionManager"),
    # Estimator: entity_backed:Estimator. Shared constant is a fallback for
    # tests that do not depend on the caller owning a specific Estimator record.
    "estimator_headers": build_user_headers("est-operator-1", "Estimator"),
}


def make_field_adjuster_headers(user_id: str) -> dict:
    """FieldAdjuster headers with an explicit (opaque) operator id."""
    return build_user_headers(user_id, "FieldAdjuster")


def make_production_manager_headers(user_id: str) -> dict:
    """ProductionManager headers with an explicit (opaque) operator id."""
    return build_user_headers(user_id, "ProductionManager")


def make_estimator_headers(user_id: str) -> dict:
    """Estimator headers (entity_backed:Estimator). Pass the acting Estimator
    record's id as user_id when a call is Estimator-ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Estimator")


def anonymous_headers() -> dict:
    """Headers with no X-User-Role (PRD §2.1: ERR_UNAUTHENTICATED)."""
    return {}
