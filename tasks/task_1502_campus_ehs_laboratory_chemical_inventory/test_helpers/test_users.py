"""Pre-built role headers for every role in the PRD (§2.1).

Identity semantics (PRD §2.1): EHSAdmin and EHSInspector carry opaque operator
identifiers; PrincipalInvestigator and LabMember must carry the id of the acting
LabWorker. Use the make_* builders with the real worker id for ownership-gated
calls; the shared constants are only for non-ownership contexts.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: canonical form, safe anywhere.
    "admin_headers": build_user_headers("ehs-admin-1", "EHSAdmin"),
    # Opaque role: default inspector identity (inspections record it as inspector_id).
    "inspector_headers": build_user_headers("insp-1", "EHSInspector"),
    # Entity-backed roles: shared constants only for non-ownership tests.
    "pi_headers": build_user_headers("test-pi-1", "PrincipalInvestigator"),
    "lab_member_headers": build_user_headers("test-member-1", "LabMember"),
}


def make_admin_headers(operator_id: str = "ehs-admin-1") -> dict:
    """EHSAdmin (opaque identity)."""
    return build_user_headers(operator_id, "EHSAdmin")


def make_inspector_headers(inspector_id: str) -> dict:
    """EHSInspector (opaque identity recorded on inspections as inspector_id)."""
    return build_user_headers(inspector_id, "EHSInspector")


def make_pi_headers(worker_id: str) -> dict:
    """PrincipalInvestigator (entity-backed: pass the acting LabWorker id)."""
    return build_user_headers(worker_id, "PrincipalInvestigator")


def make_lab_member_headers(worker_id: str) -> dict:
    """LabMember (entity-backed: pass the acting LabWorker id)."""
    return build_user_headers(worker_id, "LabMember")
