"""Pre-built role headers for every role in the PRD (§2.1).

All six roles are opaque operator roles: the X-User-ID is an opaque operator
identifier never compared to any entity's id, and authorization is purely
role-based. Shared constants are therefore the canonical form for every role —
there are no entity_backed roles and no per-instance ownership builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_clerk_headers": build_user_headers("test-intake-clerk-1", "IntakeClerk"),
    "attending_nurse_headers": build_user_headers("test-attending-nurse-1", "AttendingNurse"),
    "neonatologist_headers": build_user_headers("test-neonatologist-1", "Neonatologist"),
    "benefits_coordinator_headers": build_user_headers("test-benefits-coord-1", "BenefitsCoordinator"),
    "vital_records_officer_headers": build_user_headers("test-vital-records-1", "VitalRecordsOfficer"),
    "registry_supervisor_headers": build_user_headers("test-registry-super-1", "RegistrySupervisor"),
}


def make_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary opaque user id + role (e.g., an unknown role
    for the unauthenticated path)."""
    return build_user_headers(user_id, role)
