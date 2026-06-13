"""Pre-built role headers for every role in the PRD.

All four roles are opaque operator identities (PRD §2.1): the server never
compares X-User-ID against any resource id, so the shared constants below are
the canonical form for every call — there is no ownership gating, hence no
per-instance entity-backed builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "clinic_admin_headers": build_user_headers("test-clinic-admin-1", "ClinicAdmin"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "Scheduler"),
    "nephrologist_headers": build_user_headers("test-nephrologist-1", "Nephrologist"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
}
