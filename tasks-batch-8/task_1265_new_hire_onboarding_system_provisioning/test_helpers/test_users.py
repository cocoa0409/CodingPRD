"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "hr_admin_headers": build_user_headers("hr-admin-1", "HRAdmin"),
    "it_provisioner_headers": build_user_headers("it-prov-1", "ITProvisioner"),
    "adjudicator_headers": build_user_headers("adj-9", "BackgroundAdjudicator"),
    "payroll_ops_headers": build_user_headers("payroll-1", "PayrollOps"),
    # entity_backed roles: shared constants are only a fallback for non-ownership tests.
    "hiring_manager_headers": build_user_headers("test-manager-1", "HiringManager"),
    "buddy_headers": build_user_headers("test-buddy-1", "Buddy"),
    "new_hire_headers": build_user_headers("test-newhire-1", "NewHire"),
}


# Per-instance builders — required for entity_backed roles whenever ownership is checked.
def make_hiring_manager_headers(user_id: str) -> dict:
    """HiringManager is entity_backed:Employee — pass the manager Employee.id."""
    return build_user_headers(user_id, "HiringManager")


def make_buddy_headers(user_id: str) -> dict:
    """Buddy is entity_backed:Employee — pass the buddy Employee.id."""
    return build_user_headers(user_id, "Buddy")


def make_new_hire_headers(user_id: str) -> dict:
    """NewHire is entity_backed:NewHire — pass the NewHire.id."""
    return build_user_headers(user_id, "NewHire")


def make_hr_admin_headers(user_id: str = "hr-1") -> dict:
    """HRAdmin is opaque — pass any operator identifier to anchor initiated_by_user_id."""
    return build_user_headers(user_id, "HRAdmin")


def make_adjudicator_headers(user_id: str = "adj-9") -> dict:
    """BackgroundAdjudicator is opaque — pass any operator identifier distinct from the initiator."""
    return build_user_headers(user_id, "BackgroundAdjudicator")
