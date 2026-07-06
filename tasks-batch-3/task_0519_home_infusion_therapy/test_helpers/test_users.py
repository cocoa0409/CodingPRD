"""Pre-built role headers for every role in the PRD.

Six roles carry an opaque X-User-ID (IntakeCoordinator, Pharmacist, AuthSpecialist,
MedicalDirector, Biller, WarehouseClerk) and the shared constant is the canonical form.
The VisitingNurse role is entity-backed: its X-User-ID is the id of the acting Nurse
(PRD 2.1), so a per-instance builder is mandatory for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for opaque roles; safe for VisitingNurse only on
# tests that do not exercise the entity-backed identity.
TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("intake-001", "IntakeCoordinator"),
    "pharmacist_headers": build_user_headers("pharm-001", "Pharmacist"),
    "auth_specialist_headers": build_user_headers("auth-001", "AuthSpecialist"),
    "medical_director_headers": build_user_headers("md-001", "MedicalDirector"),
    "medical_director_2_headers": build_user_headers("md-002", "MedicalDirector"),
    "biller_headers": build_user_headers("biller-001", "Biller"),
    "warehouse_clerk_headers": build_user_headers("warehouse-001", "WarehouseClerk"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "visiting_nurse_headers": build_user_headers("nurse-fallback-001", "VisitingNurse"),
}


def make_visiting_nurse_headers(nurse_id: str) -> dict:
    """For VisitingNurse (entity_backed:Nurse). Pass the actual Nurse.id as the
    X-User-ID whenever the call is identity-gated (visit completion, adverse-event
    reporting, segregation-of-duties comparison)."""
    return build_user_headers(nurse_id, "VisitingNurse")


def make_medical_director_headers(user_id: str) -> dict:
    """For MedicalDirector (opaque). The X-User-ID is recorded as
    reported_by_user_id / compared by segregation of duties, so callers that need a
    specific director identity pass it explicitly."""
    return build_user_headers(user_id, "MedicalDirector")
