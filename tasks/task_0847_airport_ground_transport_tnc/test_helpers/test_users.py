"""Pre-built role headers for every role in the PRD (§2.1).

AirportAuthority and CurbCoordinator have opaque identities not tied to any
persisted entity, so their shared constants are the canonical form. Operator is
entity_backed: its X-User-ID must equal the acting Operator.id, so ownership-gated
calls MUST use make_operator_headers(operator_id) with the real operator id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "airport_authority_headers": build_user_headers("admin-1", "AirportAuthority"),
    "curb_coordinator_headers": build_user_headers("curb-1", "CurbCoordinator"),
    # Operator (entity_backed): shared constant is a fallback for non-ownership
    # tests only (e.g. a 401/403/404 that never reaches an ownership comparison).
    "operator_headers": build_user_headers("operator-generic", "Operator"),
}


def make_operator_headers(operator_id: str) -> dict:
    """For the Operator role (entity_backed:Operator). Pass the acting
    Operator.id as operator_id whenever the call is ownership-gated (registering
    a vehicle, queuing, dispatching, driving a trip, appealing/paying, settling)."""
    return build_user_headers(operator_id, "Operator")


def airport_authority_headers() -> dict:
    return TEST_USERS["airport_authority_headers"]


def curb_coordinator_headers() -> dict:
    return TEST_USERS["curb_coordinator_headers"]
