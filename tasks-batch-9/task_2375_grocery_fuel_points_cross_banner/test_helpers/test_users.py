"""Pre-built role headers for every role in the PRD.

Three roles are backed by a persisted `Site` (`StoreOperator`, `PumpTerminal`,
`SettlementClerk`) and one by a persisted `Member` (`Member`): for those, the
acting `X-User-ID` must be the actual entity's `id`, so tests and fixtures use
the per-instance builders below.  The remaining three roles (`ProgramAdmin`,
`LoyaltyAnalyst`, `LoyaltySupervisor`) are operator identities whose
`X-User-ID` is an opaque string, so the shared constants are the canonical form
for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers.  These are recorded where a transition writes
# them but are never compared to any entity's id.
PROGRAM_ADMIN_USER_ID = "admin-1"
SECOND_PROGRAM_ADMIN_USER_ID = "admin-2"
LOYALTY_ANALYST_USER_ID = "analyst-1"
SECOND_LOYALTY_ANALYST_USER_ID = "analyst-2"
LOYALTY_SUPERVISOR_USER_ID = "supervisor-1"
SECOND_LOYALTY_SUPERVISOR_USER_ID = "supervisor-2"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical identity.
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_USER_ID, "ProgramAdmin"),
    "second_program_admin_headers": build_user_headers(
        SECOND_PROGRAM_ADMIN_USER_ID, "ProgramAdmin"
    ),
    "loyalty_analyst_headers": build_user_headers(LOYALTY_ANALYST_USER_ID, "LoyaltyAnalyst"),
    "second_loyalty_analyst_headers": build_user_headers(
        SECOND_LOYALTY_ANALYST_USER_ID, "LoyaltyAnalyst"
    ),
    "loyalty_supervisor_headers": build_user_headers(
        LOYALTY_SUPERVISOR_USER_ID, "LoyaltySupervisor"
    ),
    "second_loyalty_supervisor_headers": build_user_headers(
        SECOND_LOYALTY_SUPERVISOR_USER_ID, "LoyaltySupervisor"
    ),
    # Entity-backed roles — these shared constants are only safe for tests that
    # do not exercise ownership (missing-header, malformed-payload, role-gate).
    "store_operator_headers": build_user_headers("site-operator-placeholder", "StoreOperator"),
    "pump_terminal_headers": build_user_headers("site-pump-placeholder", "PumpTerminal"),
    "settlement_clerk_headers": build_user_headers("site-clerk-placeholder", "SettlementClerk"),
    "member_headers": build_user_headers("member-placeholder", "Member"),
}


def make_store_operator_headers(site_id: str) -> dict:
    """For `StoreOperator` (backed by a `Site`). Pass the acting `Site.id`."""
    return build_user_headers(site_id, "StoreOperator")


def make_pump_terminal_headers(site_id: str) -> dict:
    """For `PumpTerminal` (backed by a `Site`). Pass the acting `Site.id`."""
    return build_user_headers(site_id, "PumpTerminal")


def make_settlement_clerk_headers(site_id: str) -> dict:
    """For `SettlementClerk` (backed by a `Site`). Pass the acting `Site.id`."""
    return build_user_headers(site_id, "SettlementClerk")


def make_member_headers(member_id: str) -> dict:
    """For `Member` (backed by a `Member`). Pass the acting `Member.id`."""
    return build_user_headers(member_id, "Member")


def make_program_admin_headers(user_id: str = PROGRAM_ADMIN_USER_ID) -> dict:
    """For `ProgramAdmin` — an opaque operator identifier."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_loyalty_analyst_headers(user_id: str = LOYALTY_ANALYST_USER_ID) -> dict:
    """For `LoyaltyAnalyst` — an opaque operator identifier."""
    return build_user_headers(user_id, "LoyaltyAnalyst")


def make_loyalty_supervisor_headers(user_id: str = LOYALTY_SUPERVISOR_USER_ID) -> dict:
    """For `LoyaltySupervisor` — an opaque operator identifier."""
    return build_user_headers(user_id, "LoyaltySupervisor")


ADMIN = TEST_USERS["program_admin_headers"]
ANALYST = TEST_USERS["loyalty_analyst_headers"]
SUPERVISOR = TEST_USERS["loyalty_supervisor_headers"]
