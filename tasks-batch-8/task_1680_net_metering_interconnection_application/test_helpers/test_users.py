"""Pre-built role headers for every role in the PRD (§2.1).

The Applicant role is entity-backed by Customer: ownership-gated calls must
carry the owning customer's id as X-User-ID, so callers use
make_applicant_headers(customer["id"]). The shared applicant constant is only
a fallback for tests that never exercise ownership. The operator roles are
opaque — their X-User-ID is recorded on some resources (technician_user_id,
inspector_user_id) but never compared to an entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "coordinator_headers": build_user_headers(
        "test-coordinator-1", "InterconnectionCoordinator"),
    "engineer_headers": build_user_headers(
        "test-engineer-1", "DistributionEngineer"),
    "technician_headers": build_user_headers(
        "test-technician-1", "MeterTechnician"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "program_administrator_headers": build_user_headers(
        "test-admin-1", "ProgramAdministrator"),
}


def make_applicant_headers(user_id: str) -> dict:
    """Applicant headers whose X-User-ID is the owning Customer.id — required
    for every ownership-gated call (applications, documents, inspections,
    estimate decisions)."""
    return build_user_headers(user_id, "Applicant")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "InterconnectionCoordinator")


def make_engineer_headers(user_id: str = "test-engineer-1") -> dict:
    return build_user_headers(user_id, "DistributionEngineer")


def make_technician_headers(user_id: str = "test-technician-1") -> dict:
    """MeterTechnician headers; the id is recorded as technician_user_id on
    completed exchanges, so segregation-of-duties tests pick it deliberately."""
    return build_user_headers(user_id, "MeterTechnician")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    """Inspector headers; the id is recorded as inspector_user_id and must
    differ from the exchange's technician_user_id (segregation of duties)."""
    return build_user_headers(user_id, "Inspector")


def make_administrator_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdministrator")
