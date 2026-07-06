"""Pre-built role headers for every role in the Weatherization PRD.

All four roles carry an OPAQUE identity: X-User-ID is an operator identifier not
tied to any persisted entity, so shared constants are the canonical form. The
per-role builder functions exist to control the exact X-User-ID where a workflow
records it and later compares it (auditors: the baseline tester_user_id drives
the segregation-of-duties check at verification).
"""
from prd_bench_local_runner.testing import build_user_headers


def make_program_admin_headers(user_id: str = "program-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_auditor_headers(user_id: str = "auditor-1") -> dict:
    """For the Auditor role. Pass a distinct user_id where the recorded
    tester_user_id / verifying X-User-ID identity matters (SOD at verify)."""
    return build_user_headers(user_id, "Auditor")


def make_installer_headers(user_id: str = "installer-1") -> dict:
    return build_user_headers(user_id, "Installer")


def make_homeowner_headers(user_id: str = "homeowner-1") -> dict:
    return build_user_headers(user_id, "Homeowner")


# Shared constants — canonical for opaque roles and any test not exercising a
# specific recorded identity.
TEST_USERS = {
    "program_admin_headers": make_program_admin_headers(),
    "auditor_headers": make_auditor_headers(),
    "installer_headers": make_installer_headers(),
    "homeowner_headers": make_homeowner_headers(),
}

# A request that presents no X-User-Role header at all (PRD 2.1).
ANONYMOUS_HEADERS: dict = {}
