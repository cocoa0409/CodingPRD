"""
Header builders for the six declared roles.

Every request carries `X-User-ID` and `X-User-Role`. Two roles are additionally
entity-backed and therefore cannot use a fixed placeholder identifier:

  * for `ResearchAnalyst` the `X-User-ID` must resolve to an Analyst record whose
    `status` is `ACTIVE`, so `make_research_analyst_headers` requires the id of a
    live analyst;
  * for `SalesRep` the `X-User-ID` is compared against the stored
    `sales_rep_user_ref` of the assignment being acted upon, so
    `make_sales_rep_headers` requires that reference.
"""

from typing import Dict

from prd_bench_local_runner.testing.headers import build_user_headers

from .constants import (
    ROLE_ENABLEMENT_MANAGER,
    ROLE_LEGAL_REVIEWER,
    ROLE_PRODUCT_MANAGER,
    ROLE_PROGRAM_ADMIN,
    ROLE_RESEARCH_ANALYST,
    ROLE_SALES_REP,
)

PROGRAM_ADMIN_USER_ID = "user-program-admin-001"
LEGAL_REVIEWER_USER_ID = "user-legal-reviewer-001"
ENABLEMENT_MANAGER_USER_ID = "user-enablement-manager-001"
PRODUCT_MANAGER_USER_ID = "user-product-manager-001"
SALES_REP_USER_ID = "user-sales-rep-001"
OTHER_SALES_REP_USER_ID = "user-sales-rep-002"

# Identifiers that do not resolve to any Analyst row; used to probe the
# analyst-identity gate rather than any downstream rule.
UNRESOLVABLE_ANALYST_USER_ID = "user-not-an-analyst-999"


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_research_analyst_headers(analyst_id: str) -> Dict[str, str]:
    """Headers for an analyst; `analyst_id` must be a live ACTIVE Analyst id."""
    return build_user_headers(analyst_id, ROLE_RESEARCH_ANALYST)


def make_legal_reviewer_headers(user_id: str = LEGAL_REVIEWER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LEGAL_REVIEWER)


def make_enablement_manager_headers(
    user_id: str = ENABLEMENT_MANAGER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_ENABLEMENT_MANAGER)


def make_product_manager_headers(user_id: str = PRODUCT_MANAGER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PRODUCT_MANAGER)


def make_sales_rep_headers(sales_rep_user_ref: str = SALES_REP_USER_ID) -> Dict[str, str]:
    """Headers for a rep; the reference is what assignment ownership compares to."""
    return build_user_headers(sales_rep_user_ref, ROLE_SALES_REP)


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder for parametrised role sweeps."""
    return build_user_headers(user_id, role)


def make_headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers deliberately missing `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def make_headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers deliberately missing `X-User-Role`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


TEST_USERS = {
    ROLE_PROGRAM_ADMIN: PROGRAM_ADMIN_USER_ID,
    ROLE_LEGAL_REVIEWER: LEGAL_REVIEWER_USER_ID,
    ROLE_ENABLEMENT_MANAGER: ENABLEMENT_MANAGER_USER_ID,
    ROLE_PRODUCT_MANAGER: PRODUCT_MANAGER_USER_ID,
    ROLE_SALES_REP: SALES_REP_USER_ID,
}
