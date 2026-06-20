"""Pre-built role headers for every role in the PRD.

All five roles use an opaque identity model (PRD 2.1): X-User-ID is an opaque
operator identifier never compared to any persisted entity's id. There is no
entity_backed role, so no per-instance ownership builders are needed — the
shared constants below are the canonical form for every test.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "medical_director_headers": build_user_headers("test-medical-director-1", "MedicalDirector"),
    "nurse_staff_headers": build_user_headers("test-nurse-1", "NurseStaff"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    # Unknown role — drives ERR_UNAUTHENTICATED (PRD 2.1: X-User-Role not one of
    # the recognized role names).
    "unknown_role_headers": build_user_headers("test-stranger-1", "Stranger"),
}
