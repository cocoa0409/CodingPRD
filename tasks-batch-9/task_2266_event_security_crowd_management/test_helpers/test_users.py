"""Caller identities for the eight declared roles.

Six roles are opaque: the ``X-User-ID`` value is any stable string and the
role alone decides authority. Two roles are entity backed and their user id
must be the id of a stored row:

  * PostSupervisor       -> the Guard id of the calling supervisor
  * SubcontractorLiaison -> the Subcontractor id of the calling vendor

Because entity ids only exist once a fixture has created the row, those two
roles get header BUILDERS rather than pre-baked dicts.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ─── Opaque-role caller identities ────────────────────

TEST_USERS: Dict[str, Dict[str, str]] = {
    "director_1": {"user_id": "director-1", "role": Role.SECURITY_DIRECTOR},
    "director_2": {"user_id": "director-2", "role": Role.SECURITY_DIRECTOR},
    "analyst_1": {"user_id": "analyst-1", "role": Role.RISK_ANALYST},
    "analyst_2": {"user_id": "analyst-2", "role": Role.RISK_ANALYST},
    "coordinator_1": {"user_id": "coordinator-1", "role": Role.STAFFING_COORDINATOR},
    "coordinator_2": {"user_id": "coordinator-2", "role": Role.STAFFING_COORDINATOR},
    "auditor_1": {"user_id": "auditor-1", "role": Role.CREDENTIAL_AUDITOR},
    "commander_1": {"user_id": "commander-1", "role": Role.INCIDENT_COMMANDER},
    "commander_2": {"user_id": "commander-2", "role": Role.INCIDENT_COMMANDER},
    "operator_1": {"user_id": "operator-1", "role": Role.SYSTEM_OPERATOR},
}


def _headers(key: str) -> Dict[str, str]:
    spec = TEST_USERS[key]
    return build_user_headers(spec["user_id"], spec["role"])


DIRECTOR_HEADERS = _headers("director_1")
DIRECTOR_2_HEADERS = _headers("director_2")
ANALYST_HEADERS = _headers("analyst_1")
ANALYST_2_HEADERS = _headers("analyst_2")
COORDINATOR_HEADERS = _headers("coordinator_1")
COORDINATOR_2_HEADERS = _headers("coordinator_2")
AUDITOR_HEADERS = _headers("auditor_1")
COMMANDER_HEADERS = _headers("commander_1")
COMMANDER_2_HEADERS = _headers("commander_2")
OPERATOR_HEADERS = _headers("operator_1")


# ─── Entity-backed role builders ──────────────────────


def make_post_supervisor_headers(guard_id: str) -> Dict[str, str]:
    """Headers for a PostSupervisor caller acting as the given Guard row."""
    return build_user_headers(guard_id, Role.POST_SUPERVISOR)


def make_subcontractor_liaison_headers(subcontractor_id: str) -> Dict[str, str]:
    """Headers for a SubcontractorLiaison caller acting as the given vendor row."""
    return build_user_headers(subcontractor_id, Role.SUBCONTRACTOR_LIAISON)


# ─── Ad-hoc identity helpers ──────────────────────────


def make_director_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary SecurityDirector user id."""
    return build_user_headers(user_id, Role.SECURITY_DIRECTOR)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary RiskAnalyst user id."""
    return build_user_headers(user_id, Role.RISK_ANALYST)


def make_commander_headers(user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary IncidentCommander user id."""
    return build_user_headers(user_id, Role.INCIDENT_COMMANDER)


def headers_for_role(role: str, user_id: str = "probe-user") -> Dict[str, str]:
    """Headers for any role name, used when sweeping the role table."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
