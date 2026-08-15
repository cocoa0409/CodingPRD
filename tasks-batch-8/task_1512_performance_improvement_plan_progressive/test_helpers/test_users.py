"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque HRSystemAdmin role and for tests whose
# outcome does not depend on the caller owning a subject resource.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "HRSystemAdmin"),
    # entity_backed roles: fallback only for non-ownership tests.
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "hrbp_headers": build_user_headers("test-hrbp-1", "HRBusinessPartner"),
    "counsel_headers": build_user_headers("test-counsel-1", "LegalCounsel"),
    "director_headers": build_user_headers("test-director-1", "HRDirector"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


# Per-instance builders — required for every entity_backed role
# (Manager, HRBusinessPartner, LegalCounsel, HRDirector, Employee are all
# entity_backed:Employee per PRD §2.1). Pass the actual Employee.id as user_id
# whenever the call is ownership-gated.
def make_manager_headers(user_id: str) -> dict:
    """Manager headers bound to the actual Employee.id of the acting manager."""
    return build_user_headers(user_id, "Manager")


def make_hrbp_headers(user_id: str) -> dict:
    """HRBP headers bound to the actual Employee.id of the acting HRBP."""
    return build_user_headers(user_id, "HRBusinessPartner")


def make_counsel_headers(user_id: str) -> dict:
    """LegalCounsel headers bound to the actual Employee.id of the acting counsel."""
    return build_user_headers(user_id, "LegalCounsel")


def make_director_headers(user_id: str) -> dict:
    """HRDirector headers bound to the actual Employee.id of the acting director."""
    return build_user_headers(user_id, "HRDirector")


def make_employee_headers(user_id: str) -> dict:
    """Employee headers bound to the actual Employee.id of the acting employee."""
    return build_user_headers(user_id, "Employee")
