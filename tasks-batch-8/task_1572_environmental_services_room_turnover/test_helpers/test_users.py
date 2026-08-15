"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership of a StaffMember-backed resource. Entity-backed roles (EVSTechnician,
# QualityAuditor) MUST use the per-instance builders below whenever the call is
# capability- or ownership-gated against a real StaffMember row.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "EVSAdministrator"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "EVSDispatcher"),
    "coordinator_headers": build_user_headers(
        "test-coordinator-1", "BedPlacementCoordinator"
    ),
    "ip_headers": build_user_headers("test-ip-1", "InfectionPreventionist"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # Entity-backed fallbacks: ONLY for tests that never touch a capability or
    # ownership check against a real staff row (e.g. pure 404 probes).
    "technician_headers": build_user_headers("test-tech-1", "EVSTechnician"),
    "auditor_headers": build_user_headers("test-auditor-1", "QualityAuditor"),
}


def make_technician_headers(user_id: str) -> dict:
    """EVSTechnician is entity-backed:StaffMember — pass the real StaffMember.id
    whenever the call is capability- or ownership-gated."""
    return build_user_headers(user_id, "EVSTechnician")


def make_auditor_headers(user_id: str) -> dict:
    """QualityAuditor is entity-backed:StaffMember — pass the real StaffMember.id
    whenever the call is capability- or ownership-gated."""
    return build_user_headers(user_id, "QualityAuditor")
