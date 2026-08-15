"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlanSponsor, RecordkeeperAdmin,
# PayrollProvider, Auditor) and for tests that do not exercise ownership
# (404 / 400 / role-only checks).
TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "RecordkeeperAdmin"),
    "admin2_headers": build_user_headers("test-admin-2", "RecordkeeperAdmin"),
    "sponsor_headers": build_user_headers("test-sponsor-1", "PlanSponsor"),
    "sponsor2_headers": build_user_headers("test-sponsor-2", "PlanSponsor"),
    "payroll_headers": build_user_headers("test-payroll-1", "PayrollProvider"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}


def make_participant_headers(user_id: str) -> dict:
    """For Participant (entity-backed:Participant). Pass the actual Participant.id
    as user_id whenever the call is ownership-gated (loan request, hardship create,
    document upload, withdraw, election set/restart, read own record)."""
    return build_user_headers(user_id, "Participant")


def make_sponsor_headers(user_id: str) -> dict:
    """Per-operator sponsor headers — needed when segregation-of-duties must
    distinguish two sponsor operators on the same subject."""
    return build_user_headers(user_id, "PlanSponsor")


def make_admin_headers(user_id: str) -> dict:
    """Per-operator admin headers — needed when segregation-of-duties must
    distinguish two admin operators on the same subject."""
    return build_user_headers(user_id, "RecordkeeperAdmin")


def make_payroll_headers(user_id: str) -> dict:
    """Per-operator payroll headers."""
    return build_user_headers(user_id, "PayrollProvider")


def make_auditor_headers(user_id: str) -> dict:
    """Per-operator auditor headers."""
    return build_user_headers(user_id, "Auditor")
