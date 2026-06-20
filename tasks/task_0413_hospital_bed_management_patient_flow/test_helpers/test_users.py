"""Pre-built role headers for every role in the PRD (Section 2.1).

All six roles are opaque operator identifiers: X-User-ID is never compared to
any resource's id for ownership (PRD §2.1). Therefore the shared-constant form
below is the canonical form for every role, and no entity-backed builders exist.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "flow_admin_headers": build_user_headers("test-flowadmin-1", "FlowAdmin"),
    "bed_control_headers": build_user_headers("test-bedcontrol-1", "BedControlCoordinator"),
    "charge_nurse_headers": build_user_headers("test-chargenurse-1", "ChargeNurse"),
    "transfer_agent_headers": build_user_headers("test-transferagent-1", "TransferCenterAgent"),
    "case_manager_headers": build_user_headers("test-casemanager-1", "CaseManager"),
    "evs_tech_headers": build_user_headers("test-evstech-1", "EvsTech"),
}


def make_evs_tech_headers(user_id: str) -> dict:
    """For EvsTech. The acting X-User-ID is recorded to assigned_tech_id on a
    claimed task (PRD §2.1), but identity is opaque — any handle works."""
    return build_user_headers(user_id, "EvsTech")
