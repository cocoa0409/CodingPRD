"""Pre-built role headers for every role named in the PRD (§2.1).

Four roles are entity-backed: `X-User-ID` must be the `id` of a persisted
Operator whose `role_class` matches the claimed role. For those roles always
use the per-instance builder with the real operator id — the shared constants
below only exist for tests that never reach operator resolution (for example
an unknown-role probe) or for the three opaque roles.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque roles (TrafficCoordinator, ComplianceOfficer, StationAdmin) carry an
# identifier that is never compared to any entity id, so a constant is correct.
TEST_USERS = {
    "traffic_headers": build_user_headers("traffic-desk-1", "TrafficCoordinator"),
    "compliance_headers": build_user_headers("compliance-desk-1", "ComplianceOfficer"),
    "admin_headers": build_user_headers("station-admin-1", "StationAdmin"),
    # Entity-backed roles: these constants do NOT resolve to an Operator row and
    # are only for tests asserting ERR_OPERATOR_NOT_FOUND-style behaviour.
    "master_control_headers": build_user_headers("not-an-operator-mco", "MasterControlOperator"),
    "qc_headers": build_user_headers("not-an-operator-qc", "QCTechnician"),
    "program_director_headers": build_user_headers("not-an-operator-pd", "ProgramDirector"),
    "engineer_headers": build_user_headers("not-an-operator-eng", "BroadcastEngineer"),
}


# --------------------------------------------------------------------------
# Per-instance builders — mandatory for the four entity-backed roles.
# --------------------------------------------------------------------------

def make_master_control_headers(user_id: str) -> dict:
    """MasterControlOperator: pass the id of an Operator with role_class MASTER_CONTROL."""
    return build_user_headers(user_id, "MasterControlOperator")


def make_qc_headers(user_id: str) -> dict:
    """QCTechnician: pass the id of an Operator with role_class QC."""
    return build_user_headers(user_id, "QCTechnician")


def make_program_director_headers(user_id: str) -> dict:
    """ProgramDirector: pass the id of an Operator with role_class PROGRAM_DIRECTOR."""
    return build_user_headers(user_id, "ProgramDirector")


def make_engineer_headers(user_id: str) -> dict:
    """BroadcastEngineer: pass the id of an Operator with role_class ENGINEER."""
    return build_user_headers(user_id, "BroadcastEngineer")


def make_traffic_headers(user_id: str = "traffic-desk-1") -> dict:
    """TrafficCoordinator is opaque; the identifier is never resolved."""
    return build_user_headers(user_id, "TrafficCoordinator")


def make_compliance_headers(user_id: str = "compliance-desk-1") -> dict:
    """ComplianceOfficer is opaque; the identifier is never resolved."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_admin_headers(user_id: str = "station-admin-1") -> dict:
    """StationAdmin is opaque; the identifier is never resolved."""
    return build_user_headers(user_id, "StationAdmin")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for parametrized RBAC tests."""
    return build_user_headers(user_id, role)


ADMIN = TEST_USERS["admin_headers"]
TRAFFIC = TEST_USERS["traffic_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
