"""Pre-built role headers for every role in the PRD (Section 2.1).

All four roles (Scheduler, PreOpNurse, ORManager, BillingAnalyst) use an OPAQUE
identity model: X-User-ID is an opaque operator identifier the server never
compares to any persisted entity's id. No ownership check anywhere compares a
resource's foreign key to X-User-ID; access is governed entirely by role.
Therefore shared constants are the canonical form for every role here — there
are no entity_backed roles and no per-instance header builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "preop_nurse_headers": build_user_headers("test-preopnurse-1", "PreOpNurse"),
    "or_manager_headers": build_user_headers("test-ormanager-1", "ORManager"),
    "billing_analyst_headers": build_user_headers("test-billinganalyst-1", "BillingAnalyst"),
}
