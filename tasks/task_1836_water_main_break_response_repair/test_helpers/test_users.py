"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. For the entity_backed CrewLead role, prefer make_crew_lead_headers
# with the actual Crew.id whenever the call is ownership-gated.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "crew_lead_headers": build_user_headers("test-crew-lead-1", "CrewLead"),
    "wq_officer_headers": build_user_headers("wq_officer_1", "WaterQualityOfficer"),
    "wq_officer_2_headers": build_user_headers("wq_officer_2", "WaterQualityOfficer"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "engineer_headers": build_user_headers("test-engineer-1", "PublicWorksEngineer"),
    "system_headers": build_user_headers("test-system-1", "System"),
}


def make_crew_lead_headers(user_id: str) -> dict:
    """For CrewLead (entity_backed:Crew). Pass the actual Crew.id as user_id
    whenever the call is ownership-gated (arrive/complete)."""
    return build_user_headers(user_id, "CrewLead")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_wq_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WaterQualityOfficer")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PublicWorksEngineer")


def make_system_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "System")
