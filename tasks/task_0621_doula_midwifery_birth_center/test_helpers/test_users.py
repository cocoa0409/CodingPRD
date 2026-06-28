"""Pre-built role headers for every role in the PRD.

All four roles (IntakeCoordinator, Midwife, BillingClerk, CenterAdmin) carry an
opaque identity (PRD §2.1): X-User-ID is an opaque operator id, never compared to
any entity's id. Authorization is purely role-based, so shared constants are the
canonical form for every role here.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_coordinator_headers": build_user_headers("test-intake-1", "IntakeCoordinator"),
    "midwife_headers": build_user_headers("test-midwife-1", "Midwife"),
    "billing_clerk_headers": build_user_headers("test-billing-1", "BillingClerk"),
    "center_admin_headers": build_user_headers("test-admin-1", "CenterAdmin"),
}
