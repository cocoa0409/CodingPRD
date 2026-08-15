"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Opaque roles (GrantsManager, ProgramDirector) use these as
# the canonical form. Entity-backed roles use them ONLY for calls whose success
# does not depend on the caller owning the subject resource (e.g., 400/404
# shape tests or pure admin operations). Ownership-gated calls MUST use the
# per-instance builders below with the acting StaffMember's id.
TEST_USERS = {
    "intake_specialist_headers": build_user_headers("test-intake-1", "IntakeSpecialist"),
    "supervising_attorney_headers": build_user_headers("test-supervisor-1", "SupervisingAttorney"),
    "staff_attorney_headers": build_user_headers("test-attorney-1", "StaffAttorney"),
    "paralegal_headers": build_user_headers("test-paralegal-1", "Paralegal"),
    "ethics_officer_headers": build_user_headers("test-ethics-1", "EthicsOfficer"),
    "grants_manager_headers": build_user_headers("test-grants-1", "GrantsManager"),
    "program_director_headers": build_user_headers("test-director-1", "ProgramDirector"),
}


def make_intake_specialist_headers(user_id: str) -> dict:
    """IntakeSpecialist is entity-backed: pass the acting StaffMember.id."""
    return build_user_headers(user_id, "IntakeSpecialist")


def make_supervising_attorney_headers(user_id: str) -> dict:
    """SupervisingAttorney is entity-backed: pass the acting StaffMember.id."""
    return build_user_headers(user_id, "SupervisingAttorney")


def make_staff_attorney_headers(user_id: str) -> dict:
    """StaffAttorney is entity-backed: pass the acting StaffMember.id."""
    return build_user_headers(user_id, "StaffAttorney")


def make_paralegal_headers(user_id: str) -> dict:
    """Paralegal is entity-backed: pass the acting StaffMember.id."""
    return build_user_headers(user_id, "Paralegal")


def make_ethics_officer_headers(user_id: str) -> dict:
    """EthicsOfficer is entity-backed: pass the acting StaffMember.id."""
    return build_user_headers(user_id, "EthicsOfficer")


def make_grants_manager_headers(user_id: str = "test-grants-1") -> dict:
    """GrantsManager is opaque; the id is not tied to any persisted entity."""
    return build_user_headers(user_id, "GrantsManager")


def make_program_director_headers(user_id: str = "test-director-1") -> dict:
    """ProgramDirector is opaque; the id is not tied to any persisted entity."""
    return build_user_headers(user_id, "ProgramDirector")
