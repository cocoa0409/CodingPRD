"""Pre-built role headers for every role in the PRD (§2.1).

ClinicBuyer is entity-backed by Clinic: X-User-ID is the acting clinic's id, and
ownership checks compare a resource's clinic_id against it. Ownership-gated
calls MUST use make_clinic_buyer_headers(clinic["id"]) with the real clinic id.
AccountManager, SupplyChainPlanner, ComplianceOfficer, and SystemAdmin are
opaque operator identities not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "account_manager_headers": build_user_headers("test-account-manager-1",
                                                  "AccountManager"),
    "supply_chain_planner_headers": build_user_headers("test-planner-1",
                                                       "SupplyChainPlanner"),
    "compliance_officer_headers": build_user_headers("test-compliance-1",
                                                     "ComplianceOfficer"),
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "clinic_buyer_headers": build_user_headers("test-clinic-buyer-1", "ClinicBuyer"),
}


def make_clinic_buyer_headers(clinic_id: str) -> dict:
    """For ClinicBuyer (entity_backed:Clinic). Pass the acting Clinic.id
    whenever the call is ownership-gated."""
    return build_user_headers(clinic_id, "ClinicBuyer")


def make_account_manager_headers(user_id: str = "test-account-manager-1") -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_supply_chain_planner_headers(user_id: str = "test-planner-1") -> dict:
    return build_user_headers(user_id, "SupplyChainPlanner")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_system_admin_headers(user_id: str = "test-sysadmin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")
