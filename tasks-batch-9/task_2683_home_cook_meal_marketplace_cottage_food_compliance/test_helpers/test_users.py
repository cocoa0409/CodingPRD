"""Pre-built role headers for every role in the PRD (PRD 2.1).

`Cook` is the only role whose `X-User-ID` names a persisted entity: "When
`X-User-Role` is `Cook`, `X-User-ID` is the `id` of the acting `Cook` record."
Every ownership-gated call therefore MUST use `make_cook_headers(cook["id"])`;
the shared `TEST_USERS["cook_headers"]` constant is only for tests that do not
depend on the caller owning the subject resource.

All the other roles carry opaque identifiers, but several rules compare two
opaque identifiers to each other (segregation of duties on incident
adjudication and on menu-item approval, and the diner-cancellation ownership
check), so per-role builders exist for those too and the suite uses distinct
operator ids such as `rev-1` / `rev-2` and `so-1` / `so-2`.
"""

from prd_bench_local_runner.testing import build_user_headers
from .types import Role

# --- Canonical operator identifiers used across the suite -------------------
REVIEWER_ONE = "rev-1"
REVIEWER_TWO = "rev-2"
OFFICER_ONE = "so-1"
OFFICER_TWO = "so-2"
FINANCE_ONE = "fin-1"
FINANCE_TWO = "fin-2"
ADMIN_ONE = "admin-1"
DINER_ONE = "diner-1"
DINER_TWO = "diner-2"
DINER_THREE = "diner-3"
DINER_FOUR = "diner-4"
ANON_ONE = "anon-1"


TEST_USERS = {
    # Cook is entity_backed: this shared constant never equals a real Cook.id,
    # so use it only for non-ownership assertions (missing header, bad role...).
    "cook_headers": build_user_headers("test-cook-1", Role.COOK),
    "anonymous_headers": build_user_headers(ANON_ONE, Role.ANONYMOUS),
    "diner_headers": build_user_headers(DINER_ONE, Role.DINER),
    "diner_two_headers": build_user_headers(DINER_TWO, Role.DINER),
    "diner_three_headers": build_user_headers(DINER_THREE, Role.DINER),
    "diner_four_headers": build_user_headers(DINER_FOUR, Role.DINER),
    "compliance_reviewer_headers": build_user_headers(REVIEWER_ONE, Role.COMPLIANCE_REVIEWER),
    "compliance_reviewer_two_headers": build_user_headers(REVIEWER_TWO, Role.COMPLIANCE_REVIEWER),
    "safety_officer_headers": build_user_headers(OFFICER_ONE, Role.SAFETY_OFFICER),
    "safety_officer_two_headers": build_user_headers(OFFICER_TWO, Role.SAFETY_OFFICER),
    "finance_operator_headers": build_user_headers(FINANCE_ONE, Role.FINANCE_OPERATOR),
    "finance_operator_two_headers": build_user_headers(FINANCE_TWO, Role.FINANCE_OPERATOR),
    "platform_admin_headers": build_user_headers(ADMIN_ONE, Role.PLATFORM_ADMIN),
}


def make_cook_headers(cook_id: str) -> dict:
    """For `Cook` (identity is the acting Cook record's id). Pass the real
    Cook.id whenever the call is ownership-gated."""
    return build_user_headers(cook_id, Role.COOK)


def make_diner_headers(user_id: str) -> dict:
    """For `Diner`; the id is recorded as `diner_user_id` and compared back on
    diner-initiated order cancellation."""
    return build_user_headers(user_id, Role.DINER)


def make_compliance_reviewer_headers(user_id: str) -> dict:
    """For `ComplianceReviewer`; the id is recorded as `reviewed_by_user_id`
    and `approved_by_user_id` and compared for segregation of duties."""
    return build_user_headers(user_id, Role.COMPLIANCE_REVIEWER)


def make_safety_officer_headers(user_id: str) -> dict:
    """For `SafetyOfficer`; the id is recorded as `triaged_by_user_id` and
    `adjudicated_by_user_id` and compared between those two steps."""
    return build_user_headers(user_id, Role.SAFETY_OFFICER)


def make_finance_operator_headers(user_id: str) -> dict:
    """For `FinanceOperator`; the id is recorded as `created_by_user_id`."""
    return build_user_headers(user_id, Role.FINANCE_OPERATOR)


def make_platform_admin_headers(user_id: str) -> dict:
    """For `PlatformAdmin`; opaque, but still compared for segregation of duties."""
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


def make_anonymous_headers(user_id: str = ANON_ONE) -> dict:
    """For `Anonymous`; an opaque visitor identifier the server never compares."""
    return build_user_headers(user_id, Role.ANONYMOUS)


def headers_for_role(role: str, user_id: str = "generic-user-1") -> dict:
    """Build headers for an arbitrary role name, including undeclared ones, so
    role-permission families can be parametrised."""
    return build_user_headers(user_id, role)


# Convenience aliases for the fixed operators the composite fixtures use.
ANONYMOUS_HEADERS = TEST_USERS["anonymous_headers"]
ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]
REVIEWER_ONE_HEADERS = TEST_USERS["compliance_reviewer_headers"]
REVIEWER_TWO_HEADERS = TEST_USERS["compliance_reviewer_two_headers"]
OFFICER_ONE_HEADERS = TEST_USERS["safety_officer_headers"]
OFFICER_TWO_HEADERS = TEST_USERS["safety_officer_two_headers"]
FINANCE_ONE_HEADERS = TEST_USERS["finance_operator_headers"]
DINER_ONE_HEADERS = TEST_USERS["diner_headers"]
DINER_TWO_HEADERS = TEST_USERS["diner_two_headers"]
DINER_THREE_HEADERS = TEST_USERS["diner_three_headers"]
DINER_FOUR_HEADERS = TEST_USERS["diner_four_headers"]
