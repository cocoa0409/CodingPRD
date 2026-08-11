"""Pre-built role headers for every role in the PRD (§2.1).

DistrictBuyer and CrewLead are entity-backed roles: X-User-ID must be the id of
the acting District or Crew. Use make_district_buyer_headers(district["id"]) /
make_crew_lead_headers(crew["id"]) for any ownership-gated call; the shared
fallback constants below are only for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "ContractorAdmin"),
    "contract_manager_headers": build_user_headers("test-cm-1", "ContractManager"),
    "fulfillment_coordinator_headers": build_user_headers("test-fc-1", "FulfillmentCoordinator"),
    "service_agent_headers": build_user_headers("test-sa-1", "ServiceAgent"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "district_buyer_headers": build_user_headers("test-db-1", "DistrictBuyer"),
    "crew_lead_headers": build_user_headers("test-cl-1", "CrewLead"),
}


def make_district_buyer_headers(district_id: str) -> dict:
    """DistrictBuyer is entity-backed by District: pass the real District.id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(district_id, "DistrictBuyer")


def make_crew_lead_headers(crew_id: str) -> dict:
    """CrewLead is entity-backed by Crew: pass the real Crew.id whenever the
    call is ownership-gated (PRD §2.1)."""
    return build_user_headers(crew_id, "CrewLead")
