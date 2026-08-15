"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ServiceManager, SafetyOfficer) and for
# tests that do not exercise entity-backed ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form
    "service_manager_headers": build_user_headers("test-sm-1", "ServiceManager"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only
    "plant_operator_headers": build_user_headers("test-po-1", "PlantOperator"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only
    "technician_headers": build_user_headers("test-tech-1", "Technician"),
    # opaque role: shared constant is the canonical form
    "safety_officer_headers": build_user_headers("test-so-1", "SafetyOfficer"),
}


def make_service_manager_headers(user_id: str = "test-sm-1") -> dict:
    """ServiceManager (opaque identity). user_id is not compared to any entity id."""
    return build_user_headers(user_id, "ServiceManager")


def make_plant_operator_headers(user_id: str) -> dict:
    """PlantOperator (entity_backed:CustomerSite). Pass the owning CustomerSite.id
    whenever the call is ownership-gated (own-site reads/writes, approve, receive, cancel)."""
    return build_user_headers(user_id, "PlantOperator")


def make_technician_headers(user_id: str) -> dict:
    """Technician (entity_backed:Technician). Pass the Technician.id whenever the call
    is ownership-gated (ticket start/complete)."""
    return build_user_headers(user_id, "Technician")


def make_safety_officer_headers(user_id: str = "test-so-1") -> dict:
    """SafetyOfficer (opaque identity). user_id is recorded as issuer_user_id on permits
    but never compared to an entity id."""
    return build_user_headers(user_id, "SafetyOfficer")
