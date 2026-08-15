"""Pre-built role headers for every role in the PRD.

All four roles are opaque: X-User-ID is an operator identifier never compared
to any entity id (PRD section 2.1). Shared constants are therefore the
canonical form. Builders exist so segregation-of-duties tests can pin a
specific X-User-ID per call: the workflow actor ids recorded by the server
(created_by_user_id, received_by_user_id, initiated_by_user_id) are compared
against the approving/resolving caller's X-User-ID.

Named pins used across workflows:
  OFFICER_1 -> "u-off-1" (files title changes, receives garnishments,
               initiates estate releases)
  MANAGER_2 -> "u-mgr-2" (approves / resolves what OFFICER_1 initiated)
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "ops_officer_headers": build_user_headers("u-officer-default", "OpsOfficer"),
    "ops_manager_headers": build_user_headers("u-manager-default", "OpsManager"),
    "system_headers": build_user_headers("u-system-1", "System"),
    "auditor_headers": build_user_headers("u-auditor-1", "Auditor"),
}


def make_ops_officer_headers(user_id: str) -> dict:
    """OpsOfficer headers pinned to a specific X-User-ID."""
    return build_user_headers(user_id, "OpsOfficer")


def make_ops_manager_headers(user_id: str) -> dict:
    """OpsManager headers pinned to a specific X-User-ID."""
    return build_user_headers(user_id, "OpsManager")


def make_system_headers(user_id: str) -> dict:
    """System headers pinned to a specific X-User-ID."""
    return build_user_headers(user_id, "System")


def make_auditor_headers(user_id: str) -> dict:
    """Auditor headers pinned to a specific X-User-ID."""
    return build_user_headers(user_id, "Auditor")


OFFICER = TEST_USERS["ops_officer_headers"]
MANAGER = TEST_USERS["ops_manager_headers"]
SYSTEM = TEST_USERS["system_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# Segregation-of-duties pins: the initiating/receiving/filing user and the
# approving/resolving user must differ.
OFFICER_1 = make_ops_officer_headers("u-off-1")
MANAGER_2 = make_ops_manager_headers("u-mgr-2")
