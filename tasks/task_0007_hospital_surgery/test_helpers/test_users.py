"""Pre-built role headers for every PRD role.

All roles in this PRD are opaque (X-User-ID is a free-form operator label,
recorded in audit metadata but never used as a foreign-key match against an
entity), so the shared-constant pattern is correct here for every role —
no per-instance builder is needed.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "surgical_coordinator_headers": build_user_headers(
        "test-surgical-coordinator-1", "SurgicalCoordinator"
    ),
    "department_head_headers": build_user_headers(
        "test-department-head-1", "DepartmentHead"
    ),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "billing_admin_headers": build_user_headers(
        "test-billing-admin-1", "BillingAdmin"
    ),
    "any_headers": build_user_headers("test-any-1", "Any"),
}
