"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Producer / CountyCommittee are entity-backed: use the per-instance
# builders below whenever a call is ownership- or segregation-of-duties-gated.
TEST_USERS = {
    # entity_backed:Producer — fallback for non-ownership tests only.
    "producer_headers": build_user_headers("test-producer-1", "Producer"),
    # opaque role — canonical form.
    "county_specialist_headers": build_user_headers(
        "test-specialist-1", "CountySpecialist"
    ),
    # opaque role — canonical form.
    "county_executive_director_headers": build_user_headers(
        "test-ced-1", "CountyExecutiveDirector"
    ),
    # entity_backed:Producer — fallback for non-ownership tests only.
    "county_committee_headers": build_user_headers(
        "test-committee-1", "CountyCommittee"
    ),
}


def make_producer_headers(user_id: str) -> dict:
    """For Producer (entity_backed:Producer). Pass the acting Producer.id whenever
    the call is ownership-gated (reports, elections, enrollments, appeals, ...)."""
    return build_user_headers(user_id, "Producer")


def make_county_committee_headers(user_id: str) -> dict:
    """For CountyCommittee (entity_backed:Producer). Pass the reviewing Producer.id
    whenever the call is segregation-of-duties-gated (certify / approve / adjudicate)."""
    return build_user_headers(user_id, "CountyCommittee")
