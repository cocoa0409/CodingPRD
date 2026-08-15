"""Pre-built role headers for every role in the PRD.

AirportFinance, AirportDirector, and AirportAuditor are opaque identities:
X-User-ID is never compared to a persisted entity id. SignatoryAirline is
entity-backed by Airline (X-User-ID is the acting Airline's id);
ownership-gated calls MUST use make_signatory_airline_headers with the real
airline id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "finance_headers": build_user_headers("test-finance-1", "AirportFinance"),
    "director_headers": build_user_headers("test-director-1", "AirportDirector"),
    "auditor_headers": build_user_headers("test-auditor-1", "AirportAuditor"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "airline_headers": build_user_headers("test-airline-1", "SignatoryAirline"),
}


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "AirportFinance")


def make_director_headers(user_id: str = "test-director-1") -> dict:
    return build_user_headers(user_id, "AirportDirector")


def make_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "AirportAuditor")


def make_signatory_airline_headers(airline_id: str) -> dict:
    """For SignatoryAirline (entity_backed:Airline). Pass the acting
    Airline.id whenever the call is ownership-gated."""
    return build_user_headers(airline_id, "SignatoryAirline")
