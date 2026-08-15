"""Pre-built role headers for every role in the PRD (§2.1).

UnitAdmin, SchedulingCoordinator, ReprocessingTechnician, InfectionControlNurse,
PathologyStaff, and QualityOfficer are opaque identities: X-User-ID is not tied
to any persisted entity (it is only recorded, e.g. as technician_id). Endoscopist
is entity-backed by Provider and AnesthesiaProvider is entity-backed by
AnesthesiaProvider — ownership-gated calls MUST use the per-instance builders
with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "unit_admin_headers": build_user_headers("test-admin-1", "UnitAdmin"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "SchedulingCoordinator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "endoscopist_headers": build_user_headers("test-endoscopist-1", "Endoscopist"),
    "anesthesia_provider_headers": build_user_headers("test-anesthesia-1", "AnesthesiaProvider"),
    "technician_headers": build_user_headers("tech-1", "ReprocessingTechnician"),
    "nurse_headers": build_user_headers("nurse-1", "InfectionControlNurse"),
    "pathology_headers": build_user_headers("lab-1", "PathologyStaff"),
    "quality_officer_headers": build_user_headers("test-qo-1", "QualityOfficer"),
}

# Requests carrying no user-context headers at all (PRD §2.1 header gate).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_unit_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "UnitAdmin")


def make_scheduler_headers(user_id: str = "test-scheduler-1") -> dict:
    return build_user_headers(user_id, "SchedulingCoordinator")


def make_endoscopist_headers(provider_id: str) -> dict:
    """For Endoscopist (entity-backed by Provider). Pass the acting Provider.id
    whenever the call is ownership-gated (start/assess/complete/abort/specimens)."""
    return build_user_headers(provider_id, "Endoscopist")


def make_anesthesia_provider_headers(anesthesia_provider_id: str) -> dict:
    """For AnesthesiaProvider (entity-backed by AnesthesiaProvider). Pass the
    acting AnesthesiaProvider.id whenever the call is ownership-gated."""
    return build_user_headers(anesthesia_provider_id, "AnesthesiaProvider")


def make_technician_headers(user_id: str = "tech-1") -> dict:
    """ReprocessingTechnician; the id is stored as the cycle's technician_id,
    so segregation-of-duties scenarios pass distinct ids."""
    return build_user_headers(user_id, "ReprocessingTechnician")


def make_nurse_headers(user_id: str = "nurse-1") -> dict:
    """InfectionControlNurse; the id is stored as released_by on release."""
    return build_user_headers(user_id, "InfectionControlNurse")


def make_pathology_headers(user_id: str = "lab-1") -> dict:
    """PathologyStaff; the id is stored into the specimen custody fields."""
    return build_user_headers(user_id, "PathologyStaff")


def make_quality_officer_headers(user_id: str = "test-qo-1") -> dict:
    return build_user_headers(user_id, "QualityOfficer")
