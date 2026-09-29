"""Caller identities for the five roles of PRD §2.1.

For ``ComplianceAdmin``, ``ComplianceOfficer``, ``OpsController`` and
``RegulatorAuditor`` the ``X-User-ID`` is an opaque operator identifier that is
never compared to any entity id, so fixed constants are enough. Several
segregation-of-duties chains (PRD §2.10) need two or three *distinct* officer
identifiers, which is why more than one officer id is exposed.

For ``Passenger`` the ``X-User-ID`` must be the id of the acting passenger row,
so passenger headers are built per test from the registered passenger's id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ─── Role names, spelled exactly as PRD §2.1 requires ──

ROLE_COMPLIANCE_ADMIN = "ComplianceAdmin"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_OPS_CONTROLLER = "OpsController"
ROLE_REGULATOR_AUDITOR = "RegulatorAuditor"
ROLE_PASSENGER = "Passenger"

RECOGNISED_ROLES = [
    ROLE_COMPLIANCE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_OPS_CONTROLLER,
    ROLE_REGULATOR_AUDITOR,
    ROLE_PASSENGER,
]

# ─── Opaque operator identifiers ──────────────────────

ADMIN_1 = "admin_1"
ADMIN_2 = "admin_2"
OFFICER_1 = "officer_1"
OFFICER_2 = "officer_2"
OFFICER_3 = "officer_3"
OPS_1 = "ops_1"
AUDITOR_1 = "auditor_1"

# ─── Ready-made header dicts ──────────────────────────

ADMIN_HEADERS = build_user_headers(ADMIN_1, ROLE_COMPLIANCE_ADMIN)
ADMIN_2_HEADERS = build_user_headers(ADMIN_2, ROLE_COMPLIANCE_ADMIN)
OFFICER_HEADERS = build_user_headers(OFFICER_1, ROLE_COMPLIANCE_OFFICER)
OFFICER_2_HEADERS = build_user_headers(OFFICER_2, ROLE_COMPLIANCE_OFFICER)
OFFICER_3_HEADERS = build_user_headers(OFFICER_3, ROLE_COMPLIANCE_OFFICER)
OPS_HEADERS = build_user_headers(OPS_1, ROLE_OPS_CONTROLLER)
AUDITOR_HEADERS = build_user_headers(AUDITOR_1, ROLE_REGULATOR_AUDITOR)


def make_passenger_headers(passenger_id: str) -> Dict[str, str]:
    """Headers for the ``Passenger`` role, whose X-User-ID is the passenger id."""
    return build_user_headers(passenger_id, ROLE_PASSENGER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role pair, including unknown roles."""
    return build_user_headers(user_id, role)


def headers_without_identity() -> Dict[str, str]:
    """A request carrying neither ``X-User-ID`` nor ``X-User-Role``."""
    return {"Content-Type": "application/json"}


def headers_with_empty_identity() -> Dict[str, str]:
    """A request whose two identity headers are present but empty strings."""
    return {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}


def headers_missing_role(user_id: str = ADMIN_1) -> Dict[str, str]:
    """A request carrying only ``X-User-ID``."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_missing_user_id(role: str = ROLE_COMPLIANCE_ADMIN) -> Dict[str, str]:
    """A request carrying only ``X-User-Role``."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
