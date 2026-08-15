"""Pre-built role headers for every role in the PRD (§2.1).

For the five opaque roles, X-User-ID is an operator identifier never compared to
any entity id; the shared constants below are their canonical form. For the
entity-backed Nurse role, X-User-ID IS the acting nurse's id — always build
headers with make_nurse_headers(nurse["id"]) for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles (PRD §2.1) — canonical shared constants.
    "specialist_1": build_user_headers("spec-1", "CredentialingSpecialist"),
    "specialist_2": build_user_headers("spec-2", "CredentialingSpecialist"),
    "verifier_1": build_user_headers("ver-1", "PrimarySourceVerifier"),
    "verifier_2": build_user_headers("ver-2", "PrimarySourceVerifier"),
    "manager_1": build_user_headers("mgr-1", "NurseManager"),
    "compliance_1": build_user_headers("co-1", "ComplianceOfficer"),
    "compliance_2": build_user_headers("co-2", "ComplianceOfficer"),
    "operator_1": build_user_headers("ops-1", "SystemOperator"),
    # Fallback for Nurse-role calls that are NOT ownership-gated (e.g. RBAC
    # denials). Ownership-gated calls must use make_nurse_headers(nurse_id).
    "nurse_generic": build_user_headers("test-nurse-generic", "Nurse"),
}


def make_nurse_headers(nurse_id: str) -> dict:
    """For the entity-backed Nurse role: X-User-ID must be the nurse's own id
    whenever the call is ownership-gated (packet submit/resubmit, item
    submit-evidence, own completions)."""
    return build_user_headers(nurse_id, "Nurse")
