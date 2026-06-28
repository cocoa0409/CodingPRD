"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Four of the five roles (AdminUnderwriter, ContractAdmin,
# ClaimsAdjuster, Auditor) carry opaque identities, so the shared constant is
# the canonical form for them. RepairFacility is entity-backed; its shared
# constant is a fallback for non-ownership tests only — ownership-gated calls
# must use make_repair_facility_headers(facility_id).
TEST_USERS = {
    "admin_underwriter_headers": build_user_headers("test-admin-underwriter-1", "AdminUnderwriter"),
    "contract_admin_headers": build_user_headers("test-contract-admin-1", "ContractAdmin"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", "ClaimsAdjuster"),
    "repair_facility_headers": build_user_headers("test-repair-facility-1", "RepairFacility"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_admin_underwriter_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AdminUnderwriter")


def make_contract_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ContractAdmin")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_repair_facility_headers(user_id: str) -> dict:
    """For RepairFacility (entity_backed:RepairFacility). Pass the actual
    RepairFacility.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "RepairFacility")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
