"""Pre-built role headers for every role in the PRD.

HRAdmin is an opaque role: the server never compares its X-User-ID to any
entity id. HRBusinessPartner, TalentManager, Manager, and Employee are
entity-backed roles: their X-User-ID MUST equal the id of the persisted
Employee record whenever the call is ownership-gated (consent / hold /
release-hold, nomination, calibration propose / revise, apply / withdraw /
respond-offer) or identity-compared (segregation of duties).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque role, and for tests that don't
# exercise ownership (400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "HRAdmin"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only.
    "hrbp_headers": build_user_headers("test-hrbp-1", "HRBusinessPartner"),
    "talent_manager_headers": build_user_headers("test-tm-1", "TalentManager"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


# Per-instance builders — required for every entity_backed role.
def make_hrbp_headers(user_id: str) -> dict:
    """For HRBusinessPartner (entity_backed:Employee). Pass the actual acting
    Employee.id as user_id whenever the call is identity-compared (e.g. HiPo
    endorsement segregation-of-duties)."""
    return build_user_headers(user_id, "HRBusinessPartner")


def make_talent_manager_headers(user_id: str) -> dict:
    """For TalentManager (entity_backed:Employee). Pass the actual acting
    Employee.id as user_id whenever the call is identity-compared (e.g.
    calibration ratify segregation-of-duties)."""
    return build_user_headers(user_id, "TalentManager")


def make_manager_headers(user_id: str) -> dict:
    """For Manager (entity_backed:Employee). Pass the actual manager Employee.id
    as user_id whenever the call is ownership-gated (consent / hold /
    release-hold, nomination, calibration propose / revise)."""
    return build_user_headers(user_id, "Manager")


def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the actual Employee.id as
    user_id whenever the call is ownership-gated (apply, withdraw,
    respond-offer)."""
    return build_user_headers(user_id, "Employee")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For HRAdmin (opaque). Pass a distinct user_id only to distinguish
    operators in a scenario; the server never compares it to an entity id."""
    return build_user_headers(user_id, "HRAdmin")
