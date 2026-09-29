"""Acting identities and the header builders that carry them.

Every request carries ``X-User-ID`` identifying the acting user and
``X-User-Role`` declaring the capacity in which that user is acting. The
duty-separation rules of this service compare recorded operator identities
against each other, so the user id has to be threadable independently of the
role: each ``make_*_headers`` helper takes an explicit user id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COUNCIL_CLERK,
    ROLE_DEVELOPER,
    ROLE_FINANCE_OFFICER,
    ROLE_NEXUS_ANALYST,
    ROLE_PERMIT_OFFICER,
    ROLE_PROGRAM_ADMINISTRATOR,
    UNDECLARED_ROLE,
)
from .types import Headers

# --- Canonical acting user identifiers ------------------------------------
ADMIN_1 = "admin-1"
ADMIN_2 = "admin-2"
ANALYST_1 = "analyst-1"
ANALYST_2 = "analyst-2"
CLERK_1 = "clerk-1"
CLERK_2 = "clerk-2"
PERMIT_1 = "permit-1"
DEVELOPER_1 = "dev-1"
DEVELOPER_2 = "dev-2"
FINANCE_1 = "finance-1"
FINANCE_2 = "finance-2"
# One human holding both the analyst and the clerk capacity.
DUAL_1 = "dual-1"
# A user acting under a role name this service does not declare.
ATTORNEY_1 = "attorney-1"


def make_admin_headers(user_id: str = ADMIN_1) -> Headers:
    return build_user_headers(user_id, ROLE_PROGRAM_ADMINISTRATOR)


def make_analyst_headers(user_id: str = ANALYST_1) -> Headers:
    return build_user_headers(user_id, ROLE_NEXUS_ANALYST)


def make_clerk_headers(user_id: str = CLERK_1) -> Headers:
    return build_user_headers(user_id, ROLE_COUNCIL_CLERK)


def make_permit_officer_headers(user_id: str = PERMIT_1) -> Headers:
    return build_user_headers(user_id, ROLE_PERMIT_OFFICER)


def make_developer_headers(user_id: str = DEVELOPER_1) -> Headers:
    return build_user_headers(user_id, ROLE_DEVELOPER)


def make_finance_headers(user_id: str = FINANCE_1) -> Headers:
    return build_user_headers(user_id, ROLE_FINANCE_OFFICER)


def make_undeclared_role_headers(user_id: str = ATTORNEY_1) -> Headers:
    """Headers declaring a role string outside the six the service accepts."""
    return build_user_headers(user_id, UNDECLARED_ROLE)


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary identity/role pairing."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str = ROLE_PROGRAM_ADMINISTRATOR) -> Headers:
    """Headers that omit ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str = ADMIN_1) -> Headers:
    """Headers that omit ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_blank_user_id(role: str = ROLE_PROGRAM_ADMINISTRATOR) -> Headers:
    """Headers carrying a blank ``X-User-ID`` value."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = ADMIN_1) -> Headers:
    """Headers carrying a blank ``X-User-Role`` value."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


NO_HEADERS = None
"""Sentinel meaning: send the request with no authentication headers at all."""


TEST_USERS: Dict[str, Headers] = {
    "admin": make_admin_headers(),
    "analyst": make_analyst_headers(),
    "analyst_reviewer": make_analyst_headers(ANALYST_2),
    "clerk": make_clerk_headers(),
    "permit_officer": make_permit_officer_headers(),
    "developer": make_developer_headers(),
    "other_developer": make_developer_headers(DEVELOPER_2),
    "finance": make_finance_headers(),
    "other_finance": make_finance_headers(FINANCE_2),
    "dual_analyst": make_analyst_headers(DUAL_1),
    "dual_clerk": make_clerk_headers(DUAL_1),
    "undeclared_role": make_undeclared_role_headers(),
}
