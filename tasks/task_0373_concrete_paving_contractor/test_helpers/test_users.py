"""Pre-built role headers for every role in the PRD (§2.1).

All four roles carry an OPAQUE X-User-ID that the server never compares to any
entity id. The shared constants below are therefore the canonical form for all
roles. Where a workflow audit/segregation check depends on a SPECIFIC user id
being recorded (FinanceOfficer submitting a change order or releasing a draw),
tests build distinct headers with `make_finance_officer_headers(user_id)` so the
recorded `submitted_by_user_id` / `released_by_user_id` can be made equal or
unequal as the scenario requires.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "estimator_headers": build_user_headers("estimator-1", "Estimator"),
    "project_manager_headers": build_user_headers("pm-1", "ProjectManager"),
    "finance_officer_headers": build_user_headers("fin-1", "FinanceOfficer"),
    "inspector_headers": build_user_headers("inspector-1", "Inspector"),
}


def make_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Estimator")


def make_project_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_finance_officer_headers(user_id: str) -> dict:
    """For FinanceOfficer segregation scenarios: the X-User-ID is recorded as
    submitted_by_user_id (change-order submit/resubmit) or released_by_user_id
    (draw release) and drives the §3.10/§3.11 segregation-of-duties checks."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Inspector")
