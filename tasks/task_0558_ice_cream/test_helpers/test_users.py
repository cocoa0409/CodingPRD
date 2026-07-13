"""Pre-built role headers for every role in the PRD.

All four roles (Manager, ShiftLead, Scooper, Baker) are opaque permission tiers:
`X-User-ID` is never resolved to a persisted entity or compared against any
resource id (PRD 2.1). Shared constants are therefore the canonical form for
every role — no entity_backed per-instance builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "shift_lead_headers": build_user_headers("test-shiftlead-1", "ShiftLead"),
    "scooper_headers": build_user_headers("test-scooper-1", "Scooper"),
    "baker_headers": build_user_headers("test-baker-1", "Baker"),
}
