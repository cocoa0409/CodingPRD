"""Pre-built role headers for every role in the PRD (§2.1).

ProgramCoordinator and BillingSpecialist are opaque roles: their X-User-ID is
an operator identifier not tied to any entity, so a shared constant is the
canonical form. Dietitian is entity-backed: its X-User-ID must be the id of an
actual Dietitian entity. Use make_dietitian_headers(dietitian_id) for every
dietitian call so ownership/actor stamping resolves correctly.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "coordinator_headers": build_user_headers("coordinator-ops-1", "ProgramCoordinator"),
    "billing_headers": build_user_headers("billing-rev-1", "BillingSpecialist"),
    # Fallback for non-ownership dietitian tests only (e.g. 400/404 paths).
    "dietitian_headers": build_user_headers("dietitian-shared-1", "Dietitian"),
}


def make_dietitian_headers(user_id: str) -> dict:
    """Headers for a Dietitian (entity_backed:Dietitian). Pass the actual
    Dietitian.id as user_id whenever the call records the acting educator or
    is ownership-gated."""
    return build_user_headers(user_id, "Dietitian")


def make_coordinator_headers(user_id: str = "coordinator-ops-1") -> dict:
    return build_user_headers(user_id, "ProgramCoordinator")


def make_billing_headers(user_id: str = "billing-rev-1") -> dict:
    return build_user_headers(user_id, "BillingSpecialist")
