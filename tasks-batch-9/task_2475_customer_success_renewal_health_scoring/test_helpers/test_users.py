"""Caller identities and their request headers (PRD §2.1).

PRD §2.1 draws a distinction this module encodes directly. For a `CsmUser` the
`X-User-ID` value **is** the identifier of a manager row, so a test acting as a
manager must build its headers from the `Csm.id` it just created — hence
`make_csm_headers(csm_id)`. For the other five roles the identifier is an opaque
operator string that the API only compares for equality, so a module-level
constant is enough. The two rules that compare identifiers rather than roles,
handoff ownership and segregation of duties, use the sales and executive
builders below so that a test can act as a *different* user of the same role.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ADVOCACY_MANAGER,
    ROLE_CS_EXECUTIVE,
    ROLE_CS_OPS_ADMIN,
    ROLE_CSM_USER,
    ROLE_FINANCE_ANALYST,
    ROLE_SALES_ACCOUNT_EXECUTIVE,
)

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------

OPS_ADMIN_USER_ID = "ops-1"
EXECUTIVE_USER_ID = "exec-1"
SECOND_EXECUTIVE_USER_ID = "exec-2"
FINANCE_USER_ID = "fin-1"
SALES_AE_USER_ID = "ae-7"
OTHER_SALES_AE_USER_ID = "ae-9"
ADVOCACY_USER_ID = "adv-1"

# A manager identifier that no `Csm` row will ever carry, for the cases where a
# test needs a syntactically valid `CsmUser` header without a roster row.
UNKNOWN_CSM_USER_ID = "csm-absent"

# ---------------------------------------------------------------------------
# Pre-built headers for the five opaque roles
# ---------------------------------------------------------------------------

OPS_ADMIN_HEADERS: Dict[str, str] = build_user_headers(
    OPS_ADMIN_USER_ID, ROLE_CS_OPS_ADMIN
)
EXECUTIVE_HEADERS: Dict[str, str] = build_user_headers(
    EXECUTIVE_USER_ID, ROLE_CS_EXECUTIVE
)
SECOND_EXECUTIVE_HEADERS: Dict[str, str] = build_user_headers(
    SECOND_EXECUTIVE_USER_ID, ROLE_CS_EXECUTIVE
)
FINANCE_HEADERS: Dict[str, str] = build_user_headers(
    FINANCE_USER_ID, ROLE_FINANCE_ANALYST
)
SALES_HEADERS: Dict[str, str] = build_user_headers(
    SALES_AE_USER_ID, ROLE_SALES_ACCOUNT_EXECUTIVE
)
OTHER_SALES_HEADERS: Dict[str, str] = build_user_headers(
    OTHER_SALES_AE_USER_ID, ROLE_SALES_ACCOUNT_EXECUTIVE
)
ADVOCACY_HEADERS: Dict[str, str] = build_user_headers(
    ADVOCACY_USER_ID, ROLE_ADVOCACY_MANAGER
)

# PRD §2.1: a request that omits either header is rejected before anything else.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "Content-Type": "application/json",
    "X-User-Role": ROLE_CS_OPS_ADMIN,
}
MISSING_ROLE_HEADERS: Dict[str, str] = {
    "Content-Type": "application/json",
    "X-User-ID": OPS_ADMIN_USER_ID,
}
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    OPS_ADMIN_USER_ID, "NotARealRole"
)


# ---------------------------------------------------------------------------
# Header builders
# ---------------------------------------------------------------------------


def make_csm_headers(csm_id: str) -> Dict[str, str]:
    """Headers for the manager whose roster row is `csm_id`.

    Mandatory for every `CsmUser` call: PRD §2.1 states that for this role the
    `X-User-ID` value is the identifier of the acting manager, so a shared
    constant would misidentify the caller.
    """
    return build_user_headers(csm_id, ROLE_CSM_USER)


def make_ops_admin_headers(user_id: str = OPS_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for a CS operations administrator."""
    return build_user_headers(user_id, ROLE_CS_OPS_ADMIN)


def make_executive_headers(user_id: str = EXECUTIVE_USER_ID) -> Dict[str, str]:
    """Headers for a CS executive; vary `user_id` for segregation-of-duties tests."""
    return build_user_headers(user_id, ROLE_CS_EXECUTIVE)


def make_finance_headers(user_id: str = FINANCE_USER_ID) -> Dict[str, str]:
    """Headers for a finance analyst."""
    return build_user_headers(user_id, ROLE_FINANCE_ANALYST)


def make_sales_headers(user_id: str = SALES_AE_USER_ID) -> Dict[str, str]:
    """Headers for a sales account executive; vary `user_id` for ownership tests."""
    return build_user_headers(user_id, ROLE_SALES_ACCOUNT_EXECUTIVE)


def make_advocacy_headers(user_id: str = ADVOCACY_USER_ID) -> Dict[str, str]:
    """Headers for an advocacy manager."""
    return build_user_headers(user_id, ROLE_ADVOCACY_MANAGER)


# Every role except `CsmUser`, whose headers must be derived from a roster row.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "ops_admin": OPS_ADMIN_HEADERS,
    "executive": EXECUTIVE_HEADERS,
    "finance": FINANCE_HEADERS,
    "sales": SALES_HEADERS,
    "advocacy": ADVOCACY_HEADERS,
}


def headers_for(alias: str) -> Dict[str, str]:
    """Look up a pre-built header set by alias."""
    return TEST_USERS[alias]
