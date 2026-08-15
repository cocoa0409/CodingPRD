"""Pre-built role headers for every role in the PRD.

Six roles are opaque identities: X-User-ID is not tied to any persisted
entity. AgencyCoordinator is entity-backed by PartnerAgency (X-User-ID is the
acting agency's id); ownership-gated calls MUST use make_agency_coordinator_headers
with the real agency id, never the shared fallback constant.

The default WarehouseManager identity (wm-user-1) and FinanceManager identity
(fm-user-1) differ so that purchase-order submission passes the segregation-of-
duties check by default; SoD tests construct same-identity headers explicitly.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "bank_admin_headers": build_user_headers("admin-user-1", "BankAdmin"),
    "warehouse_manager_headers": build_user_headers("wm-user-1", "WarehouseManager"),
    "finance_manager_headers": build_user_headers("fm-user-1", "FinanceManager"),
    "privacy_officer_headers": build_user_headers("po-user-1", "PrivacyOfficer"),
    "volunteer_coordinator_headers": build_user_headers("vc-user-1", "VolunteerCoordinator"),
    "volunteer_headers": build_user_headers("vol-user-1", "Volunteer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "agency_coordinator_headers": build_user_headers("test-coordinator-1", "AgencyCoordinator"),
}


def make_bank_admin_headers(user_id: str = "admin-user-1") -> dict:
    return build_user_headers(user_id, "BankAdmin")


def make_warehouse_manager_headers(user_id: str = "wm-user-1") -> dict:
    return build_user_headers(user_id, "WarehouseManager")


def make_finance_manager_headers(user_id: str = "fm-user-1") -> dict:
    return build_user_headers(user_id, "FinanceManager")


def make_agency_coordinator_headers(agency_id: str) -> dict:
    """For AgencyCoordinator (entity_backed:PartnerAgency). Pass the acting
    PartnerAgency.id whenever the call is ownership-gated."""
    return build_user_headers(agency_id, "AgencyCoordinator")


def make_privacy_officer_headers(user_id: str = "po-user-1") -> dict:
    return build_user_headers(user_id, "PrivacyOfficer")


def make_volunteer_coordinator_headers(user_id: str = "vc-user-1") -> dict:
    return build_user_headers(user_id, "VolunteerCoordinator")


def make_volunteer_headers(user_id: str = "vol-user-1") -> dict:
    return build_user_headers(user_id, "Volunteer")
