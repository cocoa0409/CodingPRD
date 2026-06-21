"""Pre-built role headers for every role in the PRD.

Per PRD §2.1: YardManager, RentalAgent and Inspector are opaque operator
identities (X-User-ID not tied to any persisted entity). Contractor is
entity-backed — its X-User-ID must equal the acting ContractorAccount.id, so
ownership-gated Contractor calls MUST use make_contractor_headers(account_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Contractor tests that do not
# exercise ownership (the shared id deliberately matches no real account).
TEST_USERS = {
    "yard_manager_headers": build_user_headers("test-yard-manager-1", "YardManager"),
    "rental_agent_headers": build_user_headers("test-rental-agent-1", "RentalAgent"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_contractor_headers(account_id: str) -> dict:
    """For the Contractor role (entity_backed:ContractorAccount). Pass the actual
    ContractorAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "Contractor")
