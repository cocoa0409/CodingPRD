"""Fixed test identities and the header builders that authenticate them.

Every caller is identified by an opaque ``X-User-ID`` plus a declared
``X-User-Role``.  Two rules in this domain compare user identifiers to each
other (a captain may not accept a sheet they issued; the officer who accepted a
declaration may not close the matching audit), so the identifiers below are
stable constants rather than throwaway values.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Role names, spelled exactly as the API expects them
# ---------------------------------------------------------------------------
ROLE_LOAD_CONTROL_ADMIN = "LoadControlAdmin"
ROLE_LOAD_CONTROLLER = "LoadController"
ROLE_RAMP_AGENT = "RampAgent"
ROLE_DG_OFFICER = "DangerousGoodsOfficer"
ROLE_CAPTAIN = "Captain"
ROLE_AUDIT_INSPECTOR = "AuditInspector"

EVERY_ROLE = [
    ROLE_LOAD_CONTROL_ADMIN,
    ROLE_LOAD_CONTROLLER,
    ROLE_RAMP_AGENT,
    ROLE_DG_OFFICER,
    ROLE_CAPTAIN,
    ROLE_AUDIT_INSPECTOR,
]

# A role name the API has never declared; used to prove that an unrecognised
# role is treated as an unauthenticated caller rather than a forbidden one.
UNDECLARED_ROLE = "FuelPlanner"

# ---------------------------------------------------------------------------
# Stable user identifiers
# ---------------------------------------------------------------------------
ADMIN_USER_ID = "admin-01"

LOAD_CONTROLLER_1 = "lc-01"
LOAD_CONTROLLER_2 = "lc-02"
RAMP_AGENT_1 = "ramp-01"
RAMP_AGENT_2 = "ramp-02"
DG_OFFICER_1 = "dg-01"
DG_OFFICER_2 = "dg-02"
CAPTAIN_1 = "cpt-01"
CAPTAIN_2 = "cpt-02"
AUDIT_INSPECTOR_1 = "ai-01"
AUDIT_INSPECTOR_2 = "ai-02"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": ADMIN_USER_ID, "role": ROLE_LOAD_CONTROL_ADMIN},
    "load_controller": {"user_id": LOAD_CONTROLLER_1, "role": ROLE_LOAD_CONTROLLER},
    "load_controller_2": {"user_id": LOAD_CONTROLLER_2, "role": ROLE_LOAD_CONTROLLER},
    "ramp_agent": {"user_id": RAMP_AGENT_1, "role": ROLE_RAMP_AGENT},
    "ramp_agent_2": {"user_id": RAMP_AGENT_2, "role": ROLE_RAMP_AGENT},
    "dg_officer": {"user_id": DG_OFFICER_1, "role": ROLE_DG_OFFICER},
    "dg_officer_2": {"user_id": DG_OFFICER_2, "role": ROLE_DG_OFFICER},
    "captain": {"user_id": CAPTAIN_1, "role": ROLE_CAPTAIN},
    "captain_2": {"user_id": CAPTAIN_2, "role": ROLE_CAPTAIN},
    "audit_inspector": {"user_id": AUDIT_INSPECTOR_1, "role": ROLE_AUDIT_INSPECTOR},
    "audit_inspector_2": {"user_id": AUDIT_INSPECTOR_2, "role": ROLE_AUDIT_INSPECTOR},
}


def headers_for(user_id: str, role: str) -> Dict[str, str]:
    """Authenticate an arbitrary identifier/role pair."""
    return build_user_headers(user_id, role)


def admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LOAD_CONTROL_ADMIN)


def load_controller_headers(user_id: str = LOAD_CONTROLLER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LOAD_CONTROLLER)


def ramp_agent_headers(user_id: str = RAMP_AGENT_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_RAMP_AGENT)


def dg_officer_headers(user_id: str = DG_OFFICER_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_DG_OFFICER)


def captain_headers(user_id: str = CAPTAIN_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CAPTAIN)


def audit_inspector_headers(user_id: str = AUDIT_INSPECTOR_1) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_AUDIT_INSPECTOR)


def undeclared_role_headers(user_id: str = "who-01") -> Dict[str, str]:
    """Headers naming a role the API has never published."""
    return build_user_headers(user_id, UNDECLARED_ROLE)


def no_auth_headers() -> Dict[str, str]:
    """No identity headers at all."""
    return {}


def headers_missing_role(user_id: str = LOAD_CONTROLLER_1) -> Dict[str, str]:
    """An identifier with no declared role."""
    return {"X-User-ID": user_id}


# Convenience pre-built header sets for the identities used most often.
ADMIN = admin_headers()
LOAD_CONTROLLER = load_controller_headers()
RAMP_AGENT = ramp_agent_headers()
DG_OFFICER = dg_officer_headers()
CAPTAIN = captain_headers()
AUDIT_INSPECTOR = audit_inspector_headers()

# One header set per role, keyed by role name, for role sweeps.
HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_LOAD_CONTROL_ADMIN: ADMIN,
    ROLE_LOAD_CONTROLLER: LOAD_CONTROLLER,
    ROLE_RAMP_AGENT: RAMP_AGENT,
    ROLE_DG_OFFICER: DG_OFFICER,
    ROLE_CAPTAIN: CAPTAIN,
    ROLE_AUDIT_INSPECTOR: AUDIT_INSPECTOR,
}
