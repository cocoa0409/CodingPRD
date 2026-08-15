"""Pre-built role headers for every role in the PRD.

Entity-backed roles (DistrictAdmin, Driver) MUST be built through the
per-instance builders below whenever the call is ownership-gated: the
X-User-ID must equal the backing entity's id (the District.id or the
Driver.id), otherwise ownership checks reject every request.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls whose outcome does
# not depend on the caller owning the subject resource (e.g. 400-on-bad-payload
# or 404-on-missing-resource probes).
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    "contractor_ops_headers": build_user_headers("test-ops-1", "ContractorOps"),
    "hr_recruiter_headers": build_user_headers("test-hr-1", "HRRecruiter"),
    "fleet_manager_headers": build_user_headers("test-fleet-1", "FleetManager"),
    "finance_clerk_headers": build_user_headers("test-finance-1", "FinanceClerk"),
    # Fallbacks for entity-backed roles; non-ownership probes only.
    "district_admin_headers": build_user_headers("test-district-1", "DistrictAdmin"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_district_admin_headers(user_id: str) -> dict:
    """DistrictAdmin is entity-backed: pass the real District.id whenever the
    call is ownership-gated (award/terminate/amend, charter create/approve/
    decline, invoice dispute, incident acknowledge/return)."""
    return build_user_headers(user_id, "DistrictAdmin")


def make_driver_headers(user_id: str) -> dict:
    """Driver is entity-backed: pass the real Driver.id whenever the call is
    ownership-gated (assignment start/complete, own record read)."""
    return build_user_headers(user_id, "Driver")


def make_system_admin_headers(user_id: str = "test-sysadmin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_contractor_ops_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "ContractorOps")


def make_hr_recruiter_headers(user_id: str = "test-hr-1") -> dict:
    return build_user_headers(user_id, "HRRecruiter")


def make_fleet_manager_headers(user_id: str = "test-fleet-1") -> dict:
    return build_user_headers(user_id, "FleetManager")


def make_finance_clerk_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceClerk")
