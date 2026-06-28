"""Pre-built role headers for every role in the PRD (§2.1).

ClinicAdmin, IntakeNurse and MedicalDirector carry an OPAQUE X-User-ID — the
server records it on resources where a workflow writes it but never compares it
to any entity's id. Their shared constants are therefore the canonical form.

Nurse is entity_backed: when X-User-Role is Nurse, X-User-ID is the id of the
acting Nurse entity, and ownership checks (start/complete) compare the
appointment's nurse_id to that header. Tests that exercise nurse ownership MUST
use make_nurse_headers(nurse["id"]) with the real created Nurse id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constants are canonical.
    "clinic_admin_headers": build_user_headers("admin-1", "ClinicAdmin"),
    "intake_nurse_headers": build_user_headers("intake-1", "IntakeNurse"),
    "medical_director_headers": build_user_headers("md-1", "MedicalDirector"),
    # entity_backed:Nurse — shared constant is a fallback for non-ownership tests
    # (e.g. 403 / 404 checks). Ownership-gated calls must use make_nurse_headers.
    "nurse_headers": build_user_headers("nurse-shared-1", "Nurse"),
}


def make_clinic_admin_headers(user_id: str) -> dict:
    """ClinicAdmin (opaque). Pass an arbitrary opaque operator id."""
    return build_user_headers(user_id, "ClinicAdmin")


def make_intake_nurse_headers(user_id: str) -> dict:
    """IntakeNurse (opaque). Pass the opaque author identifier."""
    return build_user_headers(user_id, "IntakeNurse")


def make_medical_director_headers(user_id: str) -> dict:
    """MedicalDirector (opaque). Pass the opaque director identifier (e.g. the
    medical_director_user_id signed on a standing order)."""
    return build_user_headers(user_id, "MedicalDirector")


def make_nurse_headers(user_id: str) -> dict:
    """Nurse (entity_backed:Nurse). Pass the actual Nurse.id whenever the call is
    ownership-gated (start / complete the infusion, or report an adverse event as
    the dispatched nurse)."""
    return build_user_headers(user_id, "Nurse")
