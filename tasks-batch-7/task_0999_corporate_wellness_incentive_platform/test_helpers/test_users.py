"""Pre-built role headers for every role in the PRD (§2.1, §4)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. For the entity-backed Employee role, prefer make_employee_headers()
# with the real employee id whenever the call is ownership-gated.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "benefits_admin_headers": build_user_headers("test-benefits-admin-1", "BenefitsAdmin"),
    "coach_headers": build_user_headers("coach-1", "Coach"),
    "vendor_manager_headers": build_user_headers("ops-user-1", "VendorManager"),
    # Fallback only for non-ownership Employee calls (e.g. forbidden-role probes).
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin is an opaque identity; any stable identifier works."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_benefits_admin_headers(user_id: str) -> dict:
    """BenefitsAdmin is an opaque identity; any stable identifier works."""
    return build_user_headers(user_id, "BenefitsAdmin")


def make_employee_headers(user_id: str) -> dict:
    """Employee is entity-backed: pass the real Employee.id whenever the call is
    ownership-gated (accept, HRA, screenings, participations, activity events,
    award dispute, referral decline)."""
    return build_user_headers(user_id, "Employee")


def make_coach_headers(user_id: str) -> dict:
    """Coach is opaque, but session logging and discharge compare X-User-ID to the
    referral's recorded assigned_coach_id — pass the same identifier used at engage."""
    return build_user_headers(user_id, "Coach")


def make_vendor_manager_headers(user_id: str) -> dict:
    """VendorManager is opaque, but submit records X-User-ID as submitted_by —
    pass a stable identifier when later approving under segregation of duties."""
    return build_user_headers(user_id, "VendorManager")
