"""Pre-built role headers for every role in the PRD.

QICoordinator and SettlementOfficer carry opaque X-User-ID values that the server
records (coordinator_user_id, settlement_officer_user_id) but never compares to an
entity id. They ARE compared to each other for the four-eyes segregation-of-duties
check at disbursement approval, so tests that exercise that rule MUST control the
opaque id through the per-instance builders below rather than relying on a shared
constant.

Exchanger's identity is `entity_backed:Exchanger` — for ownership-gated reads,
callers MUST pass the actual Exchanger.id via make_exchanger_headers(exchanger_id).
The shared constant is a fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for tests that do not exercise the segregation-of-duties
# comparison or Exchanger ownership.
TEST_USERS = {
    "qi_coordinator_headers": build_user_headers("test-coordinator-1", "QICoordinator"),
    "settlement_officer_headers": build_user_headers("test-officer-1", "SettlementOfficer"),
    # entity_backed role: shared constant is a non-ownership fallback only.
    "exchanger_headers": build_user_headers("test-exchanger-1", "Exchanger"),
    # Anonymous (no auth headers) for unauthenticated-path tests.
    "anonymous_headers": {},
}


def make_qi_coordinator_headers(user_id: str) -> dict:
    """For QICoordinator. Pass the opaque operator id that should be recorded as the
    exchange's coordinator_user_id (e.g. 'coord-imp'). Use the SAME id on every call
    that must act as that coordinator so segregation-of-duties comparisons line up."""
    return build_user_headers(user_id, "QICoordinator")


def make_settlement_officer_headers(user_id: str) -> dict:
    """For SettlementOfficer. Pass the opaque operator id recorded as
    settlement_officer_user_id at approval. Pass an id EQUAL to the coordinator's to
    trigger ERR_SEGREGATION_OF_DUTIES, or a DIFFERENT id for a clean four-eyes approval."""
    return build_user_headers(user_id, "SettlementOfficer")


def make_exchanger_headers(exchanger_id: str) -> dict:
    """For Exchanger (entity_backed:Exchanger). Pass the actual Exchanger.id whenever
    the read is ownership-gated."""
    return build_user_headers(exchanger_id, "Exchanger")
