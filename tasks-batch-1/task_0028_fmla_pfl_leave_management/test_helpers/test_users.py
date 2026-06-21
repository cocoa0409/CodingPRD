"""Pre-built role headers for every role in the PRD (PRD §2.1).

PRD §2.1 distinguishes opaque from entity_backed roles:
- PlatformAdmin: X-User-ID is an opaque operator identifier; the server does NOT
  compare it to any entity's id.
- HRAdmin: X-User-ID is likewise opaque.
- Employee: entity_backed — X-User-ID is the id of the acting Employee.
- HealthcareProvider: entity_backed — X-User-ID is the id of the acting
  HealthcareProvider.

For ownership-gated calls (Employee viewing their own LeaveCase, HealthcareProvider
submitting a certification under their own license), the shared TEST_USERS constant
is a fallback only — fixtures MUST instead call make_employee_headers(employee_id)
or make_provider_headers(provider_id) with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # Opaque roles — shared constants are canonical (X-User-ID not tied to any entity).
    "platform_admin_headers": build_user_headers("test-pa-1", "PlatformAdmin"),
    "hr_admin_headers": build_user_headers("test-hr-1", "HRAdmin"),
    # Entity-backed roles — shared constants are FALLBACKS for non-ownership tests
    # (e.g., 400-on-bad-payload, 404-on-missing-resource, 403-on-wrong-role). For
    # ownership-gated tests use make_employee_headers / make_provider_headers below.
    "employee_headers": build_user_headers("test-emp-1", "Employee"),
    "healthcare_provider_headers": build_user_headers("test-hp-1", "HealthcareProvider"),
}


def make_platform_admin_headers(user_id: str = "test-pa-1") -> dict:
    """Opaque PlatformAdmin headers (PRD §2.1). user_id is not bound to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_hr_admin_headers(user_id: str = "test-hr-1") -> dict:
    """Opaque HRAdmin headers (PRD §2.1). user_id is not bound to any entity."""
    return build_user_headers(user_id, "HRAdmin")


def make_employee_headers(employee_id: str) -> dict:
    """Entity-backed Employee headers (PRD §2.1).

    Pass the actual Employee.id as employee_id whenever the call is
    ownership-gated (e.g., POST /leave/cases as the acting Employee).
    """
    return build_user_headers(employee_id, "Employee")


def make_provider_headers(provider_id: str) -> dict:
    """Entity-backed HealthcareProvider headers (PRD §2.1).

    Pass the actual HealthcareProvider.id as provider_id whenever the call is
    ownership-gated (e.g., POST /leave/certifications under that provider).
    """
    return build_user_headers(provider_id, "HealthcareProvider")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
