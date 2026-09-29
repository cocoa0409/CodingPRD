"""Canonical acting identities and their request headers.

PRD §2.1 requires every request to carry `X-User-ID` and `X-User-Role`. For the
five opaque-identity roles the user id is an arbitrary operator handle that the
server only ever stores in an audit column. For a `StationCoordinator` the user
id must be the `id` of the acting `Station`, so those headers can only be built
once the station exists — use :func:`make_station_coordinator_headers`.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_FUEL_ANALYST,
    ROLE_FUEL_OPS_CONTROLLER,
    ROLE_HEDGE_ACCOUNTANT,
    ROLE_RISK_POLICY_ADMIN,
    ROLE_STATION_COORDINATOR,
    ROLE_TREASURY_RISK_MANAGER,
)

# ─── Opaque operator identifiers ──────────────────────

ADMIN_USER_ID = "u_admin_1"
ADMIN_USER_ID_ALT = "u_admin_2"
ANALYST_USER_ID = "u_analyst_1"
ANALYST_USER_ID_ALT = "u_analyst_2"
TRM_USER_ID = "u_trm_1"
TRM_USER_ID_ALT = "u_trm_2"
ACCOUNTANT_USER_ID = "u_acct_1"
OPS_USER_ID = "u_ops_1"

#: One operator who acts in two capacities, used to exercise segregation of
#: duties: the same `X-User-ID` requests and then tries to decide.
DUAL_USER_ID = "u_dual_1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": ADMIN_USER_ID, "role": ROLE_RISK_POLICY_ADMIN},
    "admin_alt": {"user_id": ADMIN_USER_ID_ALT, "role": ROLE_RISK_POLICY_ADMIN},
    "analyst": {"user_id": ANALYST_USER_ID, "role": ROLE_FUEL_ANALYST},
    "analyst_alt": {"user_id": ANALYST_USER_ID_ALT, "role": ROLE_FUEL_ANALYST},
    "treasury": {"user_id": TRM_USER_ID, "role": ROLE_TREASURY_RISK_MANAGER},
    "treasury_alt": {"user_id": TRM_USER_ID_ALT, "role": ROLE_TREASURY_RISK_MANAGER},
    "accountant": {"user_id": ACCOUNTANT_USER_ID, "role": ROLE_HEDGE_ACCOUNTANT},
    "ops": {"user_id": OPS_USER_ID, "role": ROLE_FUEL_OPS_CONTROLLER},
    "dual_analyst": {"user_id": DUAL_USER_ID, "role": ROLE_FUEL_ANALYST},
    "dual_admin": {"user_id": DUAL_USER_ID, "role": ROLE_RISK_POLICY_ADMIN},
}


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role/user-id pair."""
    return build_user_headers(user_id, role)


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_RISK_POLICY_ADMIN)


def make_analyst_headers(user_id: str = ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FUEL_ANALYST)


def make_treasury_headers(user_id: str = TRM_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TREASURY_RISK_MANAGER)


def make_accountant_headers(user_id: str = ACCOUNTANT_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_HEDGE_ACCOUNTANT)


def make_ops_headers(user_id: str = OPS_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_FUEL_OPS_CONTROLLER)


def make_station_coordinator_headers(station_id: str) -> Dict[str, str]:
    """A station's local coordinator: `X-User-ID` is the station's own `id`."""
    return build_user_headers(station_id, ROLE_STATION_COORDINATOR)


# ─── Ready-made header dicts for the common actors ─────

ADMIN = make_admin_headers()
ADMIN_ALT = make_admin_headers(ADMIN_USER_ID_ALT)
ANALYST = make_analyst_headers()
ANALYST_ALT = make_analyst_headers(ANALYST_USER_ID_ALT)
TREASURY = make_treasury_headers()
TREASURY_ALT = make_treasury_headers(TRM_USER_ID_ALT)
ACCOUNTANT = make_accountant_headers()
OPS = make_ops_headers()
DUAL_ANALYST = make_analyst_headers(DUAL_USER_ID)
DUAL_ADMIN = make_admin_headers(DUAL_USER_ID)

#: Every distinct role, keyed by role name, for role-matrix walks.
HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_RISK_POLICY_ADMIN: ADMIN,
    ROLE_FUEL_ANALYST: ANALYST,
    ROLE_TREASURY_RISK_MANAGER: TREASURY,
    ROLE_HEDGE_ACCOUNTANT: ACCOUNTANT,
    ROLE_FUEL_OPS_CONTROLLER: OPS,
}


# ─── Malformed identity headers (PRD §2.1) ────────────

def headers_missing_role(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """`X-User-Role` omitted entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = ROLE_RISK_POLICY_ADMIN) -> Dict[str, str]:
    """`X-User-ID` omitted entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(
    role: str, user_id: Optional[str] = ADMIN_USER_ID
) -> Dict[str, str]:
    """A well-formed header pair naming a role outside the six defined roles."""
    return build_user_headers(user_id, role)
