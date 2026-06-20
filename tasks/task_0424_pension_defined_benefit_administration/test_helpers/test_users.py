"""Pre-built role headers for every role in the PRD.

All three roles use an opaque identity model (PRD §2.1): X-User-ID is an operator
identifier never tied to any persisted entity, and the server never compares it to
any entity's id. Shared constants are therefore canonical for every role.

The one place X-User-ID is load-bearing is segregation of duties (PRD §3.4): an
election's submitter X-User-ID is stamped into submitted_by_user_id and compared
against the approver's X-User-ID. Tests that exercise that rule need two DISTINCT
BenefitsAdministrator user-ids, so make_benefits_admin_headers(user_id) builds
headers for an arbitrary operator id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for every (opaque) role.
TEST_USERS = {
    "plan_sponsor_headers": build_user_headers("sponsor-1", "PlanSponsor"),
    "plan_actuary_headers": build_user_headers("actuary-1", "PlanActuary"),
    "benefits_admin_headers": build_user_headers("admin-1", "BenefitsAdministrator"),
    # Two distinct administrators for segregation-of-duties workflows.
    "benefits_admin_a_headers": build_user_headers("ADM_A", "BenefitsAdministrator"),
    "benefits_admin_b_headers": build_user_headers("ADM_B", "BenefitsAdministrator"),
}


def make_benefits_admin_headers(user_id: str) -> dict:
    """Build BenefitsAdministrator headers for an arbitrary operator id.

    Use distinct ids for the submitter vs approver of an election so the
    segregation-of-duties check (submitter != approver) is satisfied or
    deliberately violated.
    """
    return build_user_headers(user_id, "BenefitsAdministrator")


def make_plan_sponsor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanSponsor")


def make_plan_actuary_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlanActuary")
