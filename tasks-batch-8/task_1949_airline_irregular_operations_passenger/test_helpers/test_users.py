"""Pre-built role headers for every role in the PRD (§2.1, §4)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the six opaque roles — X-User-ID is never compared to
# any entity's id for these roles (PRD §2.1), so a fixed identifier is safe.
TEST_USERS = {
    "ops_controller_headers": build_user_headers("test-ops-controller-1", "OpsController"),
    "duty_manager_headers": build_user_headers("test-duty-manager-1", "DutyManager"),
    "agent_headers": build_user_headers("test-agent-1", "ReaccommodationAgent"),
    "crew_scheduler_headers": build_user_headers("test-crew-scheduler-1", "CrewScheduler"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceProcessor"),
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    # Passenger is entity-backed: this shared constant is ONLY a fallback for
    # tests that never exercise ownership. Ownership-gated calls MUST use
    # make_passenger_headers(<Passenger.id>).
    "passenger_headers": build_user_headers("test-passenger-1", "Passenger"),
}


def make_passenger_headers(user_id: str) -> dict:
    """Passenger is entity-backed (X-User-ID must equal the Passenger.id).
    Pass the actual Passenger.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Passenger")


# Anonymous: no auth headers at all (for ERR_UNAUTHENTICATED tests).
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
