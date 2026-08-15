"""Pre-built role headers for every role in the PRD (§2.1).

Per PRD §2.1, every role is opaque: X-User-ID is an operator identifier never
compared to any entity's id. Shared constants are therefore the canonical form
for all seven roles. Segregation-of-duties scenarios additionally need the
*same operator id* under a *different role* (e.g. the engineer's id acting as
a Controller), so a generic builder is exposed too.
"""
from prd_bench_local_runner.testing import build_user_headers

# Operator ids used across the suite (opaque strings, PRD §2.1).
ADMIN_ID = "admin-1"
ENGINEER_ID = "eng-1"
ENGINEER2_ID = "eng-2"
SUPERVISOR_ID = "sup-1"
SUPERVISOR2_ID = "sup-2"
CONTROLLER_ID = "ctrl-1"
CONTROLLER2_ID = "ctrl-2"
CLERK_ID = "clerk-1"
RATES_ID = "rates-1"
AUDITOR_ID = "aud-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_ID, "SystemAdmin"),
    "engineer_headers": build_user_headers(ENGINEER_ID, "ProjectEngineer"),
    "engineer2_headers": build_user_headers(ENGINEER2_ID, "ProjectEngineer"),
    "supervisor_headers": build_user_headers(SUPERVISOR_ID, "WorkOrderSupervisor"),
    "supervisor2_headers": build_user_headers(SUPERVISOR2_ID, "WorkOrderSupervisor"),
    "controller_headers": build_user_headers(CONTROLLER_ID, "Controller"),
    "controller2_headers": build_user_headers(CONTROLLER2_ID, "Controller"),
    "clerk_headers": build_user_headers(CLERK_ID, "FieldClerk"),
    "rates_headers": build_user_headers(RATES_ID, "RateAnalyst"),
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
}


def make_headers(role: str, user_id: str) -> dict:
    """Build headers pairing any operator id with any role. Needed by
    segregation-of-duties tests where the *same* operator id must appear as a
    different role (PRD §2.1: roles are opaque operator identifiers)."""
    return build_user_headers(user_id, role)
