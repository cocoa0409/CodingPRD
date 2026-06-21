"""Pre-built role headers for every role in the PRD.

All four roles are operator roles whose X-User-ID is an opaque operator
identifier not tied to any persisted entity (PRD §2.1). There is no
ownership-gating, so the shared-constant headers are the canonical form for
every test; no per-instance entity-backed builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "gate_controller_headers": build_user_headers("test-gate-controller-1", "GateController"),
    "ramp_agent_headers": build_user_headers("test-ramp-agent-1", "RampAgent"),
    "slot_coordinator_headers": build_user_headers("test-slot-coordinator-1", "SlotCoordinator"),
}
