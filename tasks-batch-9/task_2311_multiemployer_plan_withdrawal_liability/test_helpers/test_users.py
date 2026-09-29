"""Caller identities for the five roles.

Four roles are opaque: any non-empty `X-User-ID` is accepted and the value is
only ever compared for the two segregation-of-duties rules, so those roles get
stable synthetic ids (plus a second id per role so that "same person twice" and
"two different people" can both be expressed).

`EmployerRepresentative` is entity-backed: the `X-User-ID` must be the id of the
owning employer, so it has no fixed constant — build its headers per employer
with `make_employer_representative_headers`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

TEST_USERS = {
    "fund_administrator": {
        "user_id": "user-fund-administrator-001",
        "role": UserRole.FUND_ADMINISTRATOR.value,
    },
    "plan_actuary": {
        "user_id": "user-plan-actuary-001",
        "role": UserRole.PLAN_ACTUARY.value,
    },
    "plan_actuary_secondary": {
        "user_id": "user-plan-actuary-002",
        "role": UserRole.PLAN_ACTUARY.value,
    },
    "plan_trustee": {
        "user_id": "user-plan-trustee-001",
        "role": UserRole.PLAN_TRUSTEE.value,
    },
    "plan_trustee_secondary": {
        "user_id": "user-plan-trustee-002",
        "role": UserRole.PLAN_TRUSTEE.value,
    },
    "arbitrator": {
        "user_id": "user-arbitrator-001",
        "role": UserRole.ARBITRATOR.value,
    },
}


def headers_for(key: str) -> Dict[str, str]:
    """Headers for one of the opaque-identity test users."""
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pair."""
    return build_user_headers(user_id, role)


def make_employer_representative_headers(employer_id: str) -> Dict[str, str]:
    """Headers for the representative of a specific employer.

    The employer's own id is the caller identity, which is what the ownership
    check compares against the employer reached by the request.
    """
    return build_user_headers(employer_id, UserRole.EMPLOYER_REPRESENTATIVE.value)


FUND_ADMINISTRATOR_HEADERS = headers_for("fund_administrator")
PLAN_ACTUARY_HEADERS = headers_for("plan_actuary")
PLAN_ACTUARY_SECONDARY_HEADERS = headers_for("plan_actuary_secondary")
PLAN_TRUSTEE_HEADERS = headers_for("plan_trustee")
PLAN_TRUSTEE_SECONDARY_HEADERS = headers_for("plan_trustee_secondary")
ARBITRATOR_HEADERS = headers_for("arbitrator")

NO_ROLE_HEADERS = {"X-User-ID": "user-anonymous-001", "Content-Type": "application/json"}
NO_USER_HEADERS = {
    "X-User-Role": UserRole.FUND_ADMINISTRATOR.value,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers("user-unknown-001", "ChiefGardener")
