"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (AttendingAnesthesiologist, CRNA) get a per-instance
builder: pass the actual Provider.id as user_id for any ownership-gated call.
Opaque roles use the shared constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership (400-schema / 404-existence / RBAC-deny probes).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "GroupAdministrator"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "physician_headers": build_user_headers("test-physician-1", "AttendingAnesthesiologist"),
    "crna_headers": build_user_headers("test-crna-1", "CRNA"),
    "billing_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    "auditor_headers": build_user_headers("test-auditor-1", "ComplianceAuditor"),
}


# Per-instance builders — required for the entity_backed roles whenever the
# call is ownership-gated (assignment accept/decline, attestation submit).
def make_physician_headers(user_id: str) -> dict:
    """For AttendingAnesthesiologist (entity_backed: Provider). Pass the actual
    Provider.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AttendingAnesthesiologist")


def make_crna_headers(user_id: str) -> dict:
    """For CRNA (entity_backed: Provider). Pass the actual Provider.id whenever
    the call is ownership-gated."""
    return build_user_headers(user_id, "CRNA")


def make_headers(user_id: str, role: str) -> dict:
    """Generic header builder for arbitrary (user_id, role) pairs."""
    return build_user_headers(user_id, role)
