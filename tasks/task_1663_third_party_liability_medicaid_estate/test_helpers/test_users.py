"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use opaque operator identifiers: the PRD states that `X-User-ID`
is "an opaque operator identifier not tied to any persisted entity", so the
shared constants below are safe for every call. Per-instance builders are still
provided for tests that need a second operator of the same role (for example
the segregation-of-duties scenarios of §3.4 and §3.7).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin_1", "SystemAdmin"),
    "specialist_headers": build_user_headers("spec_1", "RecoverySpecialist"),
    "supervisor_headers": build_user_headers("sup_1", "RecoverySupervisor"),
    "supervisor2_headers": build_user_headers("sup_2", "RecoverySupervisor"),
    "accountant_headers": build_user_headers("acct_1", "RecoveryAccountant"),
    "estate_officer_headers": build_user_headers("ero_1", "EstateRecoveryOfficer"),
}

# Request carrying no operator identity headers (PRD §2.1 negative case).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_admin_headers(user_id: str) -> dict:
    """SystemAdmin headers for an arbitrary operator id (opaque role)."""
    return build_user_headers(user_id, "SystemAdmin")


def make_specialist_headers(user_id: str) -> dict:
    """RecoverySpecialist headers for an arbitrary operator id (opaque role)."""
    return build_user_headers(user_id, "RecoverySpecialist")


def make_supervisor_headers(user_id: str) -> dict:
    """RecoverySupervisor headers for an arbitrary operator id (opaque role)."""
    return build_user_headers(user_id, "RecoverySupervisor")


def make_accountant_headers(user_id: str) -> dict:
    """RecoveryAccountant headers for an arbitrary operator id (opaque role)."""
    return build_user_headers(user_id, "RecoveryAccountant")


def make_estate_officer_headers(user_id: str) -> dict:
    """EstateRecoveryOfficer headers for an arbitrary operator id (opaque role)."""
    return build_user_headers(user_id, "EstateRecoveryOfficer")
