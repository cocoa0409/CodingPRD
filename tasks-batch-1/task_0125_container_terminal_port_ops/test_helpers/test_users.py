"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, X-User-ID is an opaque operator identifier for every one of the
six roles — none is backed by a persisted entity, and ownership is never
decided by matching X-User-ID against a resource's id. Every role therefore
uses a shared-constant header dict; there are no entity-backed roles and so no
per-instance header builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "terminal_admin_headers": build_user_headers("admin-1", "TerminalAdmin"),
    "berth_planner_headers": build_user_headers("berth-1", "BerthPlanner"),
    "yard_planner_headers": build_user_headers("yard-1", "YardPlanner"),
    "gate_operator_headers": build_user_headers("gate-1", "GateOperator"),
    "customs_officer_headers": build_user_headers("customs-1", "CustomsOfficer"),
    "reefer_technician_headers": build_user_headers("reefer-1", "ReeferTechnician"),
}


def headers_missing_role():
    """Auth headers with no X-User-Role (and no X-User-ID) — for the
    ERR_UNAUTHENTICATED test. Only Content-Type is sent."""
    return {"Content-Type": "application/json"}
