"""Pre-built role headers for every role in the Intercity Ticketing PRD.

Four of the five roles carry an opaque X-User-ID (ScheduleManager, FareAnalyst,
GateAgent, SupportAgent) — the server never compares it to any entity id, so the
shared constant is the canonical form for those. The Passenger role is
entity_backed: X-User-ID must equal the acting Passenger's own id whenever the
call is ownership-gated, so a per-instance builder is provided.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles, and safe for any test that does
# not exercise Passenger ownership (e.g., 401/403/404/422 negatives).
TEST_USERS = {
    "schedule_manager_headers": build_user_headers("test-sm-1", "ScheduleManager"),
    "fare_analyst_headers": build_user_headers("test-fa-1", "FareAnalyst"),
    "gate_agent_headers": build_user_headers("test-ga-1", "GateAgent"),
    "support_agent_headers": build_user_headers("test-sa-1", "SupportAgent"),
    # Passenger shared constant: a fallback for non-ownership tests only
    # (e.g., a forbidden-role negative). Ownership-gated calls MUST use
    # make_passenger_headers(passenger["id"]) instead.
    "passenger_headers": build_user_headers("test-passenger-1", "Passenger"),
}


def make_passenger_headers(user_id: str) -> dict:
    """For the Passenger role (entity_backed:Passenger). Pass the acting
    Passenger's own `id` as user_id whenever the call is ownership-gated
    (create/confirm/pay/cancel/exchange/baggage/accessibility on owned resources).
    """
    return build_user_headers(user_id, "Passenger")


# Convenience accessors for the opaque roles.
def schedule_manager_headers() -> dict:
    return TEST_USERS["schedule_manager_headers"]


def fare_analyst_headers() -> dict:
    return TEST_USERS["fare_analyst_headers"]


def gate_agent_headers() -> dict:
    return TEST_USERS["gate_agent_headers"]


def support_agent_headers() -> dict:
    return TEST_USERS["support_agent_headers"]
