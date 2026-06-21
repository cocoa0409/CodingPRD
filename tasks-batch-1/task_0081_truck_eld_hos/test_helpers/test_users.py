"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (CarrierAdmin, SafetyOfficer), and for
# Driver-role tests that do NOT exercise ownership (e.g. 401/404/RBAC-denial paths).
#
# CarrierAdmin and SafetyOfficer are opaque: X-User-ID is never compared to any
# entity id, so a constant is the canonical form. The Driver shared constant is a
# fallback only; ownership-gated Driver calls MUST use make_driver_headers(driver_id).
TEST_USERS = {
    "carrier_admin_headers": build_user_headers("test-carrier-admin", "CarrierAdmin"),
    "safety_officer_headers": build_user_headers("test-safety-officer", "SafetyOfficer"),
    "driver_headers": build_user_headers("test-driver-fallback", "Driver"),
}


def make_driver_headers(driver_id: str) -> dict:
    """For the Driver role (entity_backed:Driver). Pass the actual Driver.id as
    X-User-ID whenever the call is ownership-gated (login, logout, append duty
    event, certify daily log, file adverse claim)."""
    return build_user_headers(driver_id, "Driver")


def make_carrier_admin_headers(user_id: str = "test-carrier-admin") -> dict:
    return build_user_headers(user_id, "CarrierAdmin")


def make_safety_officer_headers(user_id: str = "test-safety-officer") -> dict:
    return build_user_headers(user_id, "SafetyOfficer")
