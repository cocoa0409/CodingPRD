"""Pre-built role headers for every role in the PRD.

All three roles (Cashier, ShiftLead, Manager) carry an opaque identity: the
X-User-ID is never compared to any resource id, so shared constants are the
canonical form for every call (authorization is purely role-based).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "cashier_headers": build_user_headers("test-cashier-1", "Cashier"),
    "shiftlead_headers": build_user_headers("test-shiftlead-1", "ShiftLead"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
}
