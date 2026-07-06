"""Pre-built role headers for every role in the PRD.

The five roles are: IntakeCoordinator, WoundClinician, HyperbaricTech,
PayerLiaison, AttendingPhysician.

Per PRD §2.1: when X-User-Role is WoundClinician or HyperbaricTech, X-User-ID
is the id of the acting Clinician (entity-backed). For IntakeCoordinator,
PayerLiaison, and AttendingPhysician, X-User-ID is an opaque operator identifier
not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that don't exercise
# clinician ownership/provenance. WoundClinician / HyperbaricTech shared
# constants are fallbacks for non-ownership tests only.
TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "wound_clinician_headers": build_user_headers("test-wound-1", "WoundClinician"),
    "hyperbaric_tech_headers": build_user_headers("test-tech-1", "HyperbaricTech"),
    "payer_liaison_headers": build_user_headers("test-payer-1", "PayerLiaison"),
    "attending_physician_headers": build_user_headers("test-attending-1", "AttendingPhysician"),
}


# Per-instance builders — required for the entity-backed clinician roles.
def make_wound_clinician_headers(user_id: str) -> dict:
    """For WoundClinician (X-User-ID == acting Clinician.id). Pass the actual
    Clinician.id whenever the call records/consults provenance (e.g.
    performed_by_user_id on debridement completion)."""
    return build_user_headers(user_id, "WoundClinician")


def make_hyperbaric_tech_headers(user_id: str) -> dict:
    """For HyperbaricTech (X-User-ID == acting Clinician.id)."""
    return build_user_headers(user_id, "HyperbaricTech")


def make_intake_coordinator_headers(user_id: str) -> dict:
    """For IntakeCoordinator (opaque operator id)."""
    return build_user_headers(user_id, "IntakeCoordinator")


def make_payer_liaison_headers(user_id: str) -> dict:
    """For PayerLiaison (opaque operator id)."""
    return build_user_headers(user_id, "PayerLiaison")


def make_attending_physician_headers(user_id: str) -> dict:
    """For AttendingPhysician (opaque operator id, but recorded as
    initiated_by_user_id and consulted in the segregation-of-duties check)."""
    return build_user_headers(user_id, "AttendingPhysician")
