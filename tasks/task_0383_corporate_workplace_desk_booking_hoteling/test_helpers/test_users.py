"""Pre-built role headers for every role in the PRD.

The PRD recognizes exactly four roles: FacilityManager, Employee, Receptionist,
Analyst. Only Employee is entity-backed (X-User-ID is the acting Employee's id);
FacilityManager, Receptionist, and Analyst are opaque operators whose X-User-ID
is not compared to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the three opaque operator roles, and for any test
# that does not exercise Employee ownership (e.g. 401/403/404/422 negative cases).
TEST_USERS = {
    "facility_manager_headers": build_user_headers("test-fm-1", "FacilityManager"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "receptionist_headers": build_user_headers("test-reception-1", "Receptionist"),
    "analyst_headers": build_user_headers("test-analyst-1", "Analyst"),
}


def make_employee_headers(user_id: str) -> dict:
    """For the entity-backed Employee role. Pass the actual Employee.id as
    user_id whenever the call is ownership-gated: creating a reservation
    (employee_id must equal X-User-ID), checking in / completing / cancelling
    an owned reservation, managing own amenity lines, or hosting/approving a
    visitor pass (host_employee_id must equal X-User-ID)."""
    return build_user_headers(user_id, "Employee")


def make_facility_manager_headers(user_id: str = "test-fm-1") -> dict:
    """FacilityManager is opaque; X-User-ID is an operator identifier."""
    return build_user_headers(user_id, "FacilityManager")


def make_receptionist_headers(user_id: str = "test-reception-1") -> dict:
    """Receptionist is opaque; X-User-ID is an operator identifier."""
    return build_user_headers(user_id, "Receptionist")


def make_analyst_headers(user_id: str = "test-analyst-1") -> dict:
    """Analyst is opaque; X-User-ID is an operator identifier."""
    return build_user_headers(user_id, "Analyst")
