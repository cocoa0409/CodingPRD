"""Pre-built role headers for every role in the PRD (§2.1).

Payee is entity-backed: for ownership-gated calls use make_payee_headers() with
the actual Payee.id. The shared payee_headers constant is only a fallback for
tests that do not exercise ownership. The opaque staff roles also get per-id
builders because segregation-of-duties rules compare X-User-ID values recorded
on resources (PRD §2.9) — distinct ids are required to exercise both sides.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque staff roles: the X-User-ID is not tied to any persisted entity.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "operations_specialist_headers": build_user_headers("ops-1", "OperationsSpecialist"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "judicial_recorder_headers": build_user_headers("jr-1", "JudicialRecorder"),
    # Read-only umbrella role (PRD §2.1): any authenticated caller may read.
    "reader_headers": build_user_headers("reader-1", "Any"),
    # Entity-backed role: fallback constant for non-ownership tests only.
    "payee_headers": build_user_headers("test-payee-1", "Payee"),
}


def make_payee_headers(user_id: str) -> dict:
    """Payee is entity-backed (PRD §2.1): X-User-ID must be the Payee.id
    whenever the call is ownership-gated (change requests, petition draft/file/withdraw)."""
    return build_user_headers(user_id, "Payee")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_case_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CaseManager")


def make_operations_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsSpecialist")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_judicial_recorder_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "JudicialRecorder")
