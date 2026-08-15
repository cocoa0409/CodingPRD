"""Pre-built role headers for every role in the PRD (§2.1).

BusinessOwner is entity-backed: its X-User-ID must be the id of the acting
BusinessOwner record whenever the call is ownership-gated. Use
make_business_owner_headers(owner_id) for those calls; the shared constant is
only for reads or non-ownership-gated checks.
"""
from prd_bench_local_runner.testing import build_user_headers

OFFICER_A = "officer-a"
OFFICER_B = "officer-b"
MANAGER_1 = "manager-1"
MANAGER_2 = "manager-2"
SECRETARY_1 = "secretary-1"
ADMIN_1 = "admin-1"

# Shared constants — safe for opaque roles and for tests that do not exercise
# BusinessOwner ownership.
TEST_USERS = {
    "officer_a_headers": build_user_headers(OFFICER_A, "ComplianceOfficer"),
    "officer_b_headers": build_user_headers(OFFICER_B, "ComplianceOfficer"),
    "manager_1_headers": build_user_headers(MANAGER_1, "ComplianceManager"),
    "manager_2_headers": build_user_headers(MANAGER_2, "ComplianceManager"),
    "secretary_1_headers": build_user_headers(SECRETARY_1, "BoardSecretary"),
    "admin_1_headers": build_user_headers(ADMIN_1, "PlatformAdmin"),
    # Fallback for BusinessOwner calls that are NOT ownership-gated (e.g. 400/404 probes).
    "business_owner_headers": build_user_headers("test-business-owner-1", "BusinessOwner"),
}


def make_business_owner_headers(user_id: str) -> dict:
    """BusinessOwner is entity-backed: pass the actual BusinessOwner.id whenever
    the call is ownership-gated (assessment start/submit, plan writes, evidence)."""
    return build_user_headers(user_id, "BusinessOwner")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceManager")


def make_secretary_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BoardSecretary")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
