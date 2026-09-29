"""Pre-built header dictionaries for every declared role.

Six roles carry an opaque actor identifier; the Contractor and Operator roles are
entity backed, so the acting identifier must be the id of the row they own and
their headers have to be built per entity.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_AWARD_AUTHORITY,
    ROLE_CONTRACTOR,
    ROLE_DETERMINATION_REVIEWER,
    ROLE_FIELD_INSPECTOR,
    ROLE_FUNDING_OFFICER,
    ROLE_OPERATOR,
    ROLE_PROCUREMENT_OFFICER,
    ROLE_PROGRAM_ADMIN,
    U_ADMIN,
    U_AWARD,
    U_FUNDING_1,
    U_FUNDING_2,
    U_INSPECTOR,
    U_PROCUREMENT,
    U_PROCUREMENT_2,
    U_PROCUREMENT_3,
    U_REVIEWER,
    U_REVIEWER_2,
)

ADMIN = build_user_headers(U_ADMIN, ROLE_PROGRAM_ADMIN)
INSPECTOR = build_user_headers(U_INSPECTOR, ROLE_FIELD_INSPECTOR)
REVIEWER = build_user_headers(U_REVIEWER, ROLE_DETERMINATION_REVIEWER)
REVIEWER_2 = build_user_headers(U_REVIEWER_2, ROLE_DETERMINATION_REVIEWER)
PROCUREMENT = build_user_headers(U_PROCUREMENT, ROLE_PROCUREMENT_OFFICER)
PROCUREMENT_2 = build_user_headers(U_PROCUREMENT_2, ROLE_PROCUREMENT_OFFICER)
PROCUREMENT_3 = build_user_headers(U_PROCUREMENT_3, ROLE_PROCUREMENT_OFFICER)
AWARD = build_user_headers(U_AWARD, ROLE_AWARD_AUTHORITY)
FUNDING = build_user_headers(U_FUNDING_1, ROLE_FUNDING_OFFICER)
FUNDING_2 = build_user_headers(U_FUNDING_2, ROLE_FUNDING_OFFICER)

# The award authority acting under the procurement officer's own identifier, used
# to exercise the duty-separation comparison rather than the role membership one.
AWARD_AS_PROCUREMENT = build_user_headers(U_PROCUREMENT, ROLE_AWARD_AUTHORITY)


def make_contractor_headers(contractor_id: str) -> dict:
    """Headers for the entity backed Contractor role, scoped to one contractor."""
    return build_user_headers(contractor_id, ROLE_CONTRACTOR)


def make_operator_headers(operator_id: str) -> dict:
    """Headers for the entity backed Operator role, scoped to one operator."""
    return build_user_headers(operator_id, ROLE_OPERATOR)


def headers_without_role(user_id: str) -> dict:
    """A request that carries an actor identifier but no role header at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user(role: str) -> dict:
    """A request that names a role but carries no actor identifier."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str, role: str = "Auditor") -> dict:
    """A request naming a role the contract never declares."""
    return build_user_headers(user_id, role)
