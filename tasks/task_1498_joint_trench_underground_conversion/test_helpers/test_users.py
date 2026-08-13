"""Pre-built role headers for every role in the PRD (§2.1).

UtilityCoordinator is entity-backed: when a call is ownership-gated
(participation transitions, slot creation/transitions, invoice pay/dispute),
the caller's X-User-ID must be the participation's own id — use
make_coordinator_headers(participation_id), never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "pm_headers": build_user_headers("pm-1", "ProgramManager"),
    "row_headers": build_user_headers("row-1", "RightOfWayAgent"),
    "contractor_headers": build_user_headers("cc-1", "ConversionContractor"),
    "finance_headers": build_user_headers("fin-1", "FinanceAnalyst"),
    # Fallback for the entity-backed role — non-ownership contexts only.
    "coordinator_headers": build_user_headers("coordinator-1", "UtilityCoordinator"),
}

# Headers with no X-User-Role at all (authentication-failure probes).
NO_ROLE_HEADERS = {
    "X-User-ID": "anon-1",
    "Content-Type": "application/json",
}


def make_coordinator_headers(participation_id: str) -> dict:
    """UtilityCoordinator is entity-backed: pass the participation's own id
    whenever the call is ownership-gated."""
    return build_user_headers(participation_id, "UtilityCoordinator")


def make_pm_headers(user_id: str) -> dict:
    """ProgramManager is opaque; distinct ids matter for segregation of duties."""
    return build_user_headers(user_id, "ProgramManager")


def make_finance_headers(user_id: str) -> dict:
    """FinanceAnalyst is opaque; the id lands on submitted_by_user_id / created_by_user_id."""
    return build_user_headers(user_id, "FinanceAnalyst")


def make_row_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RightOfWayAgent")


def make_contractor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConversionContractor")
